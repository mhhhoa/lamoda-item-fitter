"""Главное окно: список файлов слева, настройки справа, кнопка снизу."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..core.compressor import Status
from ..core.jobs import collect
from ..core.settings import INPUT_EXTENSIONS, Settings
from ..pipeline import Pipeline, Summary
from .model import THUMB_SIZE, FileTableModel
from .settings_panel import SettingsPanel
from .widgets import DropZone, human_size

PANEL_WIDTH = 372


class MainWindow(QWidget):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.setObjectName("root")
        self.setWindowTitle("Lamoda Item Fitter — сжатие фото под маркетплейс")
        self.setMinimumSize(1200, 660)
        self.resize(1320, 820)
        self.setAcceptDrops(True)

        self.model = FileTableModel(self)
        self.pipeline = Pipeline(self)
        self.pipeline.item_done.connect(self._on_item_done)
        self.pipeline.progress.connect(self._on_progress)
        self.pipeline.finished.connect(self._on_finished)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(self._build_body(), 1)
        root.addWidget(self._build_footer())

        self._refresh_summary()

    # ------------------------------------------------------------------
    # Сборка интерфейса
    # ------------------------------------------------------------------
    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(64)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        mark = QLabel("L")
        mark.setObjectName("logoMark")
        mark.setAlignment(Qt.AlignCenter)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("Lamoda Item Fitter")
        title.setObjectName("appTitle")
        subtitle = QLabel("Пакетное сжатие фотографий под требования маркетплейса")
        subtitle.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)

        layout.addWidget(mark)
        layout.addLayout(titles)
        layout.addStretch(1)
        return header

    def _build_body(self) -> QWidget:
        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(12)

        self.drop_zone = DropZone()
        self.drop_zone.dropped.connect(self.add_paths)
        self.drop_zone.browse_files.connect(self._browse_files)
        self.drop_zone.browse_folder.connect(self._browse_folder)
        left.addWidget(self.drop_zone)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.list_label = QLabel("Список пуст")
        self.list_label.setObjectName("hint")
        self.remove_button = QPushButton("Убрать выбранные")
        self.clear_button = QPushButton("Очистить")
        self.clear_button.setObjectName("danger")
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear)
        toolbar.addWidget(self.list_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self.remove_button)
        toolbar.addWidget(self.clear_button)
        left.addLayout(toolbar)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(THUMB_SIZE + 12)
        self.table.setIconSize(self.table.iconSize().scaled(THUMB_SIZE, THUMB_SIZE, Qt.KeepAspectRatio))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(self._reveal_row)

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setMinimumSectionSize(52)
        # Имя файла тянется за шириной окна, остальное держит заданный размер.
        fixed = {
            FileTableModel.COL_THUMB: THUMB_SIZE + 12,
            FileTableModel.COL_BEFORE: 84,
            FileTableModel.COL_AFTER: 84,
            FileTableModel.COL_SAVED: 84,
        }
        for column, width in fixed.items():
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.table.setColumnWidth(column, width)
        for column, width in (
            (FileTableModel.COL_FOLDER, 104),
            (FileTableModel.COL_STATUS, 200),
        ):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(FileTableModel.COL_NAME, QHeaderView.Stretch)
        left.addWidget(self.table, 1)

        self.panel = SettingsPanel(self.settings)
        self.panel.changed.connect(self._on_settings_changed)

        scroll = QScrollArea()
        scroll.setWidget(self.panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll.setFrameShape(QScrollArea.NoFrame)
        # Считаем ширину по содержимому: при другом системном шрифте или
        # масштабе интерфейса фиксированное число обрезало бы поля ввода.
        needed = self.panel.sizeHint().width() + scroll.verticalScrollBar().sizeHint().width() + 4
        scroll.setFixedWidth(max(PANEL_WIDTH, min(needed, PANEL_WIDTH + 120)))

        layout.addLayout(left, 1)
        layout.addWidget(scroll)
        return body

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setObjectName("footer")
        footer.setFixedHeight(72)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(16)

        summary = QVBoxLayout()
        summary.setSpacing(3)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("summaryStrong")
        self.detail_label = QLabel()
        self.detail_label.setObjectName("summary")
        summary.addWidget(self.summary_label)
        summary.addWidget(self.detail_label)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(220)
        self.progress.setVisible(False)

        self.open_button = QPushButton("Открыть папку")
        self.open_button.setVisible(False)
        self.open_button.clicked.connect(self._open_output)

        self.start_button = QPushButton("Сжать")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._toggle_run)

        layout.addLayout(summary)
        layout.addStretch(1)
        layout.addWidget(self.progress)
        layout.addWidget(self.open_button)
        layout.addWidget(self.start_button)
        return footer

    # ------------------------------------------------------------------
    # Добавление файлов
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and not self.pipeline.running:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()

    def add_paths(self, paths: list[Path]) -> None:
        if self.pipeline.running:
            return
        jobs = collect(paths)
        if not jobs:
            self.detail_label.setText("В добавленном нет подходящих картинок")
            return
        added = self.model.add_jobs(jobs)
        skipped = len(jobs) - added
        self._refresh_summary()
        if skipped:
            self.detail_label.setText(f"Добавлено {added}, повторов пропущено: {skipped}")

    def _browse_files(self) -> None:
        patterns = " ".join(f"*{extension}" for extension in sorted(INPUT_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Выберите фотографии", str(Path.home()), f"Изображения ({patterns})"
        )
        if files:
            self.add_paths([Path(f) for f in files])

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку с фотографиями", str(Path.home())
        )
        if folder:
            self.add_paths([Path(folder)])

    def _remove_selected(self) -> None:
        if self.pipeline.running:
            return
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        self.model.remove_rows(list(rows))
        self._refresh_summary()

    def _clear(self) -> None:
        if self.pipeline.running:
            return
        self.model.clear()
        self.open_button.setVisible(False)
        self._refresh_summary()

    # ------------------------------------------------------------------
    # Контекстное меню и открытие папок
    # ------------------------------------------------------------------
    def _context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        menu = QMenu(self)
        reveal = QAction("Показать в папке", self)
        reveal.triggered.connect(lambda: self._reveal_row(index))
        menu.addAction(reveal)
        remove = QAction("Убрать из списка", self)
        remove.setEnabled(not self.pipeline.running)
        remove.triggered.connect(self._remove_selected)
        menu.addAction(remove)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _reveal_row(self, index) -> None:
        if not index.isValid():
            return
        row = self.model.rows[index.row()]
        target = row.job.source
        if row.result is not None and row.result.destination is not None:
            target = row.result.destination
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

    def _open_output(self) -> None:
        if self.settings.output_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.settings.output_dir))

    # ------------------------------------------------------------------
    # Запуск
    # ------------------------------------------------------------------
    def _on_settings_changed(self) -> None:
        self.settings = self.panel.collect()
        self._refresh_summary()

    def _toggle_run(self) -> None:
        if self.pipeline.running:
            self.pipeline.cancel()
            self.start_button.setEnabled(False)
            self.start_button.setText("Останавливаю…")
            return
        self._start()

    def _start(self) -> None:
        self.settings = self.panel.collect()
        if not self.model.rows:
            return

        if not self.settings.output_dir:
            folder = QFileDialog.getExistingDirectory(
                self, "Куда складывать результат", str(Path.home())
            )
            if not folder:
                return
            self.panel.output_field.setText(folder)
            self.settings = self.panel.collect()

        output = Path(self.settings.output_dir)
        try:
            output.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            QMessageBox.warning(
                self, "Не получилось", f"Не удалось создать папку выгрузки:\n{error}"
            )
            return

        self.settings.save()
        self.model.reset_results()
        self.open_button.setVisible(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(self.model.rows))
        self.progress.setValue(0)
        self.panel.set_busy(True)
        self.drop_zone.setEnabled(False)
        self.remove_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self.start_button.setText("Стоп")
        self.pipeline.start(self.model.jobs(), self.settings)

    def _on_item_done(self, index: int, result) -> None:
        self.model.set_result(index, result)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.summary_label.setText(f"Обработано {done} из {total}")

    def _on_finished(self, summary: Summary) -> None:
        self.panel.set_busy(False)
        self.drop_zone.setEnabled(True)
        self.remove_button.setEnabled(True)
        self.clear_button.setEnabled(True)
        self.start_button.setEnabled(True)
        self.start_button.setText("Сжать")
        self.progress.setVisible(False)
        self.open_button.setVisible(bool(self.settings.output_dir))

        if summary.cancelled:
            self.summary_label.setText("Остановлено")
            self.detail_label.setText(f"Успели обработать {summary.processed} из {summary.total}")
            return

        saved = max(0, summary.source_bytes - summary.output_bytes)
        percent = 100 * saved / summary.source_bytes if summary.source_bytes else 0
        self.summary_label.setText(
            f"Готово · {human_size(summary.source_bytes)} → {human_size(summary.output_bytes)}"
        )

        details = [f"Файлов: {summary.total}", f"Экономия {percent:.0f}%"]
        if summary.too_big:
            details.append(f"не влезли в лимит: {summary.too_big}")
        if summary.skipped:
            details.append(f"пропущено: {summary.skipped}")
        if summary.errors:
            details.append(f"ошибок: {summary.errors}")
        self.detail_label.setText(" · ".join(details))

    # ------------------------------------------------------------------
    def _refresh_summary(self) -> None:
        count = len(self.model.rows)
        total = self.model.total_size()
        self.remove_button.setEnabled(count > 0 and not self.pipeline.running)
        self.clear_button.setEnabled(count > 0 and not self.pipeline.running)
        self.start_button.setEnabled(count > 0)

        if not count:
            self.drop_zone.set_compact(False)
            self.list_label.setText("Список пуст")
            self.summary_label.setText("Добавьте фотографии")
            self.detail_label.setText("Можно перетащить папку целиком")
            return

        self.drop_zone.set_compact(True)
        self.list_label.setText(f"{count} {_plural(count)} · {human_size(total)}")
        self.summary_label.setText(f"{count} {_plural(count)} · {human_size(total)}")

        limit = self.settings.target_bytes
        if limit is None:
            self.detail_label.setText("Лимит по весу выключен")
            return
        heavy = sum(1 for row in self.model.rows if row.size > limit)
        if heavy:
            self.detail_label.setText(
                f"Тяжелее лимита: {heavy} — их и будем ужимать"
            )
        else:
            self.detail_label.setText("Все файлы уже укладываются в лимит")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.pipeline.running:
            answer = QMessageBox.question(
                self, "Обработка идёт",
                "Остановить обработку и закрыть программу?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.pipeline.cancel()
        # Задача, дописывающая файл, эмитит сигнал в уже разрушенное окно —
        # так теряется и результат, и приложение целиком.
        self.pipeline.wait()
        self.model.clear()
        self.panel.collect().save()
        event.accept()


def _plural(count: int) -> str:
    if 11 <= count % 100 <= 14:
        return "файлов"
    return {1: "файл", 2: "файла", 3: "файла", 4: "файла"}.get(count % 10, "файлов")
