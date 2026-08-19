"""Главное окно.

Экран один: куда бросить файлы, что с ними стало и куда это легло. Всё
остальное — за шестерёнкой.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QRunnable, QObject, QThreadPool, Signal
from PySide6.QtGui import QIcon, QImage, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..batch import COPY, FAILED, Job, Outcome, apply_policy, conflicts, plan
from ..config import Preset
from ..downloads import downloads_dir, open_folder
from ..fitter import FITTED, PASSTHROUGH, SKIPPED
from ..imageio import is_supported
from .preview import PreviewView
from .settings import SettingsDialog
from .theme import current_palette, stylesheet
from .worker import BatchWorker

APP_NAME = "Lamoda Item Fitter"
ROLE_JOB = Qt.ItemDataRole.UserRole
ROLE_OUTCOME = Qt.ItemDataRole.UserRole + 1

STATUS_TEXT = {
    FITTED: "готово",
    PASSTHROUGH: "перенесён без подгонки",
    SKIPPED: "пропущен",
    FAILED: "ошибка",
}


def _load_scaled(path: Path, box: QSize) -> QImage:
    """Читает изображение сразу уменьшенным — полноразмерные кадры тяжёлые."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and (size.width() > box.width() or size.height() > box.height()):
        scaled = size.scaled(box, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(scaled)
    return reader.read()


class _ThumbSignals(QObject):
    ready = Signal(object, QImage)


class _ThumbTask(QRunnable):
    def __init__(self, item: QTreeWidgetItem, path: Path) -> None:
        super().__init__()
        self.signals = _ThumbSignals()
        self._item = item
        self._path = path

    def run(self) -> None:
        image = _load_scaled(self._path, QSize(96, 96))
        if not image.isNull():
            self.signals.ready.emit(self._item, image)


class DropZone(QFrame):
    """Область для перетаскивания и две кнопки выбора."""

    dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(104)

        title = QLabel("Перетащите сюда файлы или папку")
        title.setObjectName("dropTitle")
        hint = QLabel("JPG, PNG, WEBP, TIFF — папки обрабатываются со всей вложенностью")
        hint.setObjectName("hint")

        self.pick_files = QPushButton("Выбрать файлы")
        self.pick_folder = QPushButton("Выбрать папку")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.pick_files)
        buttons.addWidget(self.pick_folder)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.addStretch(1)
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def _set_hover(self, hover: bool) -> None:
        self.setProperty("hover", "true" if hover else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_hover(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_hover(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_hover(False)
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()
                 if url.isLocalFile()]
        paths = [p for p in paths if p.is_dir() or (p.is_file() and is_supported(p))]
        if paths:
            self.dropped.emit(paths)
            event.acceptProposedAction()


class MainWindow(QWidget):
    def __init__(self, preset: Preset) -> None:
        super().__init__()
        self._preset = preset
        self._palette = current_palette()
        self._output_root: Path | None = None
        self._conflict = COPY
        self._jobs: list[Job] = []
        self._sources: list[Path] = []
        self._thread: QThread | None = None
        self._worker: BatchWorker | None = None
        self._pool = QThreadPool()

        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1020, 720)
        self.setStyleSheet(stylesheet(self._palette))
        self._build()
        self._refresh_controls()

    # --- сборка окна ---------------------------------------------------------

    def _build(self) -> None:
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        subtitle = QLabel("Подгонка предметных фото под правила Ламоды: "
                          f"{self._preset.canvas.width}×{self._preset.canvas.height}, "
                          f"отступ снизу {self._preset.margins.bottom}")
        subtitle.setObjectName("subtitle")
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(title)
        heading.addWidget(subtitle)

        self.settings_button = QPushButton("Настройки")
        self.settings_button.clicked.connect(self._open_settings)
        header = QHBoxLayout()
        header.addLayout(heading)
        header.addStretch(1)
        header.addWidget(self.settings_button)

        self.drop = DropZone()
        self.drop.dropped.connect(self.add_paths)
        self.drop.pick_files.clicked.connect(self._pick_files)
        self.drop.pick_folder.clicked.connect(self._pick_folder)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Файл", "Ракурс", "Статус"])
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(44, 44))
        self.tree.setAlternatingRowColors(False)
        # обрезаем слева: имя файла важнее пути к нему
        self.tree.setTextElideMode(Qt.TextElideMode.ElideLeft)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(lambda *_: self._update_preview())

        self.preview = PreviewView(self._preset, self._palette)
        self.before_toggle = QCheckBox("Показать исходник")
        self.before_toggle.toggled.connect(self.preview.show_before)
        preview_box = QVBoxLayout()
        preview_box.setContentsMargins(0, 0, 0, 0)
        preview_box.addWidget(self.preview, 1)
        preview_box.addWidget(self.before_toggle, alignment=Qt.AlignmentFlag.AlignCenter)
        preview_panel = QFrame()
        preview_panel.setObjectName("card")
        preview_panel.setLayout(preview_box)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([600, 400])

        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(200)
        self.progress.hide()

        self.output_button = QPushButton()
        self.output_button.setObjectName("link")
        self.output_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.output_button.clicked.connect(lambda: open_folder(self._destination()))

        self.clear_button = QPushButton("Очистить")
        self.clear_button.clicked.connect(self._clear)
        self.run_button = QPushButton("Обработать")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self._toggle_run)

        footer = QHBoxLayout()
        footer.addWidget(self.output_button)
        footer.addStretch(1)
        footer.addWidget(self.progress)
        footer.addWidget(self.clear_button)
        footer.addWidget(self.run_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addWidget(self.drop)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.status)
        layout.addLayout(footer)

    # --- работа со списком ---------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        paths = [p for p in paths if p.is_dir() or (p.is_file() and is_supported(p))]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()

    def add_paths(self, paths: list[Path]) -> None:
        known = set(self._sources)
        self._sources.extend(p for p in paths if p not in known)
        self._rebuild_queue()

    def _rebuild_queue(self) -> None:
        self.tree.clear()
        self._jobs = plan(self._sources, self._preset, output_root=self._output_root)
        for job in self._jobs:
            item = QTreeWidgetItem([job.title, "", "в очереди"])
            item.setData(0, ROLE_JOB, job)
            item.setToolTip(0, str(job.source))
            self.tree.addTopLevelItem(item)
            task = _ThumbTask(item, job.source)
            task.signals.ready.connect(self._set_thumbnail)
            self._pool.start(task)
        self._refresh_controls()
        if self._jobs:
            self.status.setText(f"В очереди {len(self._jobs)} файлов.")
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _set_thumbnail(self, item: QTreeWidgetItem, image: QImage) -> None:
        try:
            item.setIcon(0, QIcon(QPixmap.fromImage(image)))
        except RuntimeError:
            pass  # строку успели удалить, пока грузилась миниатюра

    def _clear(self) -> None:
        self._sources.clear()
        self._jobs.clear()
        self.tree.clear()
        self.preview.clear()
        self.status.setText("")
        self._refresh_controls()

    def _destination(self) -> Path:
        return self._output_root or downloads_dir()

    def _refresh_controls(self) -> None:
        running = self._thread is not None
        self.run_button.setEnabled(bool(self._jobs) or running)
        self.run_button.setText("Отмена" if running else "Обработать")
        self.clear_button.setEnabled(bool(self._jobs) and not running)
        self.settings_button.setEnabled(not running)
        self.output_button.setText(f"Результат: {self._destination()}")

    # --- выбор файлов и настройки -------------------------------------------

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Выберите фото", "",
            "Изображения (*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp)")
        if files:
            self.add_paths([Path(f) for f in files])

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с фото")
        if folder:
            self.add_paths([Path(folder)])

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._preset, self._output_root, self._conflict, self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self._preset = dialog.result_preset()
            self._conflict = dialog.result_conflict()
            self._output_root = dialog.result_output()
            self.preview._preset = self._preset
            self._rebuild_queue()

    # --- запуск --------------------------------------------------------------

    def _toggle_run(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("Останавливаю…")
            self.run_button.setEnabled(False)
            return
        self._start()

    def _ask_conflicts(self, jobs: list[Job]) -> str | None:
        clashing = conflicts(jobs)
        if not clashing:
            return self._conflict
        box = QMessageBox(self)
        box.setWindowTitle("Файлы уже существуют")
        box.setText(f"В папке назначения уже есть {len(clashing)} файлов с такими именами.")
        box.setInformativeText("Что с ними сделать?")
        copy = box.addButton("Сохранить копией", QMessageBox.ButtonRole.AcceptRole)
        overwrite = box.addButton("Перезаписать", QMessageBox.ButtonRole.DestructiveRole)
        skip = box.addButton("Пропустить", QMessageBox.ButtonRole.RejectRole)
        box.addButton("Отмена", QMessageBox.ButtonRole.NoRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is copy:
            return "copy"
        if clicked is overwrite:
            return "overwrite"
        if clicked is skip:
            return "skip"
        return None

    def _start(self) -> None:
        if not self._jobs:
            return
        policy = self._ask_conflicts(self._jobs)
        if policy is None:
            return
        jobs, skipped = apply_policy(self._jobs, policy)
        for job in skipped:
            item = self._item_for(job)
            if item is not None:
                item.setText(2, "пропущен — файл уже есть")
        if not jobs:
            self.status.setText("Все файлы уже есть в папке назначения.")
            return

        for job in jobs:
            item = self._item_for(job)
            if item is not None:
                item.setData(0, ROLE_JOB, job)
                item.setText(2, "обработка…")

        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText("Обрабатываю…")

        self._counts = {}
        self._cancelled = False
        self._worker = BatchWorker(jobs, self._preset)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.produced.connect(self._on_outcome)
        self._worker.progressed.connect(lambda done, total: self.progress.setValue(done))
        # поток останавливает себя сам, а прибираемся уже по его finished:
        # звать wait() из обработчика сигнала воркера — значит ждать самого себя
        self._worker.completed.connect(self._on_finished)
        self._worker.completed.connect(self._thread.quit)
        self._thread.finished.connect(self._on_thread_done)
        self._thread.start()
        self._refresh_controls()

    def _item_for(self, job: Job) -> QTreeWidgetItem | None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            stored: Job = item.data(0, ROLE_JOB)
            if stored is not None and stored.source == job.source:
                return item
        return None

    def _on_outcome(self, outcome: Outcome) -> None:
        item = self._item_for(outcome.job)
        if item is None:
            return
        item.setData(0, ROLE_JOB, outcome.job)
        item.setData(0, ROLE_OUTCOME, outcome)
        item.setText(1, outcome.metrics.angle_label or "—")
        text = STATUS_TEXT.get(outcome.status, outcome.status)
        if outcome.warnings:
            text += f" · {len(outcome.warnings)} замечан." if len(outcome.warnings) > 1 else " · замечание"
        item.setText(2, text)
        tooltip = [outcome.reason] if outcome.reason else []
        tooltip += outcome.warnings
        if outcome.status == FITTED:
            margins = outcome.metrics.margins
            tooltip.append(f"отступы: низ {margins.get('bottom')}, "
                           f"слева {margins.get('left')}, справа {margins.get('right')}")
        item.setToolTip(2, "\n".join(tooltip))
        colors = {FITTED: self._palette.success, PASSTHROUGH: self._palette.muted,
                  SKIPPED: self._palette.warning, FAILED: self._palette.danger}
        from PySide6.QtGui import QBrush, QColor

        item.setForeground(2, QBrush(QColor(colors.get(outcome.status, self._palette.text))))
        if item is self.tree.currentItem():
            self._update_preview()

    def _on_finished(self, counts: dict) -> None:
        self._counts = counts
        self._cancelled = self._worker is not None and self._worker.cancelled

    def _on_thread_done(self) -> None:
        thread, worker = self._thread, self._worker
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()

        counts = getattr(self, "_counts", {})
        cancelled = getattr(self, "_cancelled", False)
        self.progress.hide()
        parts = [f"подогнано {counts.get(FITTED, 0)}"]
        if counts.get(PASSTHROUGH):
            parts.append(f"перенесено без подгонки {counts[PASSTHROUGH]}")
        if counts.get(SKIPPED):
            parts.append(f"пропущено {counts[SKIPPED]}")
        if counts.get(FAILED):
            parts.append(f"ошибок {counts[FAILED]}")
        prefix = "Остановлено. " if cancelled else "Готово. "
        # путь и так висит слева в футере — незачем повторять его здесь
        self.status.setText(prefix + ", ".join(parts) + ".")
        self._refresh_controls()
        self._update_preview()

    # --- превью --------------------------------------------------------------

    def _update_preview(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            self.preview.clear()
            return
        job: Job = item.data(0, ROLE_JOB)
        outcome: Outcome | None = item.data(0, ROLE_OUTCOME)
        box = QSize(900, 1300)
        before = _load_scaled(job.source, box) if job else None
        after = None
        caption = "исходник — ещё не обработан"
        if outcome is not None and outcome.written and outcome.job.destination.exists():
            after = _load_scaled(outcome.job.destination, box)
            margins = outcome.metrics.margins
            caption = (f"результат · низ {margins.get('bottom')} · "
                       f"поля {margins.get('left')}/{margins.get('right')}"
                       if margins else "результат")
        elif outcome is not None:
            caption = outcome.reason or "не обработан"
        self.before_toggle.setEnabled(after is not None)
        if after is None:
            self.before_toggle.setChecked(False)
        self.preview.set_images(before, after, caption)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None:
            self._worker.cancel()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        event.accept()


def main(argv: list[str] | None = None) -> int:
    import sys

    application = QApplication(argv if argv is not None else sys.argv)
    application.setApplicationName(APP_NAME)
    application.setOrganizationName(APP_NAME)
    window = MainWindow(Preset.load())
    window.show()
    return application.exec()
