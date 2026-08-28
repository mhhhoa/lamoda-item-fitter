"""Главное окно: список файлов слева, настройки справа, кнопка снизу."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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

from .. import APP_NAME, APP_TAGLINE
from ..core.jobs import collect
from ..core.settings import INPUT_EXTENSIONS, THEME_DARK, THEME_LIGHT, Settings
from ..pipeline import Pipeline, Summary
from .model import THUMB_SIZE, FileTableModel
from .preview import PreviewDialog
from .settings_panel import SettingsPanel
from .theme import stylesheet
from .widgets import DropZone, human_size

PANEL_WIDTH = 372


class MainWindow(QWidget):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.setObjectName("root")
        self.setWindowTitle(f"{APP_NAME} — сжатие и подгонка размеров фотографий")
        self.setMinimumSize(1200, 660)
        self.resize(1340, 840)
        self.setAcceptDrops(True)

        self.model = FileTableModel(self)
        self.model.theme = settings.theme
        self.model.checked_changed.connect(self._refresh_summary)
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

        self._install_shortcuts()
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

        mark = QLabel("IF")
        mark.setObjectName("logoMark")
        mark.setAlignment(Qt.AlignCenter)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        subtitle = QLabel(APP_TAGLINE)
        subtitle.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)

        self.theme_button = QPushButton()
        self.theme_button.setObjectName("themeToggle")
        self.theme_button.setCursor(Qt.PointingHandCursor)
        self.theme_button.clicked.connect(self._toggle_theme)
        self._sync_theme_button()

        layout.addWidget(mark)
        layout.addLayout(titles)
        layout.addStretch(1)
        layout.addWidget(self.theme_button)
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
        self.check_all_button = QPushButton("Отметить все")
        self.uncheck_all_button = QPushButton("Снять все")
        self.remove_button = QPushButton("Убрать выбранные")
        self.clear_button = QPushButton("Очистить")
        self.clear_button.setObjectName("danger")
        self.check_all_button.clicked.connect(lambda: self.model.set_all_checked(True))
        self.uncheck_all_button.clicked.connect(lambda: self.model.set_all_checked(False))
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear)
        toolbar.addWidget(self.list_label)
        toolbar.addStretch(1)
        for button in (
            self.check_all_button, self.uncheck_all_button,
            self.remove_button, self.clear_button,
        ):
            toolbar.addWidget(button)
        left.addLayout(toolbar)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(THUMB_SIZE + 12)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(self._open_preview_at)
        self.table.clicked.connect(self._on_cell_clicked)

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setMinimumSectionSize(52)
        fixed = {
            # В первой колонке живут галочка и миниатюра — им нужно место.
            FileTableModel.COL_THUMB: THUMB_SIZE + 40,
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
        needed = self.panel.sizeHint().width() + scroll.verticalScrollBar().sizeHint().width() + 4
        scroll.setFixedWidth(max(PANEL_WIDTH, min(needed, PANEL_WIDTH + 120)))

        layout.addLayout(left, 1)
        layout.addWidget(scroll)
        return body

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setObjectName("footer")
        footer.setFixedHeight(82)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 10, 20, 12)
        layout.setSpacing(16)

        summary = QVBoxLayout()
        summary.setSpacing(2)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("summaryStrong")
        # Вместо подсказок — живая ссылка на папку, куда всё уедет.
        self.path_link = QPushButton()
        self.path_link.setObjectName("pathLink")
        self.path_link.setCursor(Qt.PointingHandCursor)
        self.path_link.clicked.connect(self._open_output)
        summary.addWidget(self.summary_label)
        summary.addWidget(self.path_link, 0, Qt.AlignLeft)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(220)
        self.progress.setVisible(False)

        self.preview_button = QPushButton("Предпросмотр")
        self.preview_button.clicked.connect(self._open_preview_selected)

        self.start_button = QPushButton("Сжать")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._toggle_run)

        layout.addLayout(summary)
        layout.addStretch(1)
        layout.addWidget(self.progress)
        layout.addWidget(self.preview_button)
        layout.addWidget(self.start_button)
        return footer

    def _install_shortcuts(self) -> None:
        space = QShortcut(QKeySequence(Qt.Key_Space), self.table)
        space.setContext(Qt.WidgetShortcut)
        space.activated.connect(self._toggle_selected_checks)

    # ------------------------------------------------------------------
    # Тема
    # ------------------------------------------------------------------
    def _sync_theme_button(self) -> None:
        light = self.settings.theme == THEME_LIGHT
        self.theme_button.setText("☀" if light else "☾")
        self.theme_button.setToolTip(
            "Переключить на тёмную тему" if light else "Переключить на светлую тему"
        )

    def _toggle_theme(self) -> None:
        self.settings.theme = THEME_LIGHT if self.settings.theme == THEME_DARK else THEME_DARK
        self.model.theme = self.settings.theme
        self._sync_theme_button()
        application = QApplication.instance()
        if application is not None:
            application.setStyleSheet(stylesheet(self.settings.theme))
        self.model.refresh_all()
        self.settings.save()

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
            self.summary_label.setText("В добавленном нет подходящих картинок")
            return
        self.model.add_jobs(jobs)
        self._refresh_summary()

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

    def _selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def _remove_selected(self) -> None:
        if self.pipeline.running:
            return
        self.model.remove_rows(self._selected_rows())
        self._refresh_summary()

    def _clear(self) -> None:
        if self.pipeline.running:
            return
        self.model.clear()
        self._refresh_summary()

    def _toggle_selected_checks(self) -> None:
        rows = self._selected_rows()
        if rows:
            self.model.toggle_checked(rows)

    def _on_cell_clicked(self, index) -> None:
        """Клик по галочке внутри выделения переключает всё выделение сразу."""
        toggled = self.model.take_last_toggled()
        if toggled is None or toggled != index.row():
            return
        rows = self._selected_rows()
        if len(rows) > 1 and index.row() in rows:
            self.model.set_checked(rows, self.model.rows[index.row()].checked)

    # ------------------------------------------------------------------
    # Контекстное меню, предпросмотр, папки
    # ------------------------------------------------------------------
    def _context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        menu = QMenu(self)
        preview = QAction("Предпросмотр до/после", self)
        preview.triggered.connect(lambda: self._open_preview(index.row()))
        menu.addAction(preview)
        reveal = QAction("Показать в папке", self)
        reveal.triggered.connect(lambda: self._reveal_row(index))
        menu.addAction(reveal)
        menu.addSeparator()
        toggle = QAction("Снять или поставить галочку", self)
        toggle.triggered.connect(self._toggle_selected_checks)
        menu.addAction(toggle)
        remove = QAction("Убрать из списка", self)
        remove.setEnabled(not self.pipeline.running)
        remove.triggered.connect(self._remove_selected)
        menu.addAction(remove)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _open_preview_at(self, index) -> None:
        if index.isValid():
            self._open_preview(index.row())

    def _open_preview_selected(self) -> None:
        rows = self._selected_rows()
        self._open_preview(rows[0] if rows else 0)

    def _open_preview(self, row: int) -> None:
        if not (0 <= row < len(self.model.rows)):
            return
        self.settings = self.panel.collect()
        PreviewDialog(self.model.rows[row].job.source, self.settings, self).exec()

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
        else:
            self.panel.choose_output()

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
        jobs = self.model.checked_jobs()
        if not jobs:
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

        # Цифры этого прогона должны пережить закрытие программы.
        self.settings.save()
        self.model.reset_results()
        self.progress.setVisible(True)
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.panel.set_busy(True)
        self.drop_zone.setEnabled(False)
        for button in (
            self.remove_button, self.clear_button,
            self.check_all_button, self.uncheck_all_button, self.preview_button,
        ):
            button.setEnabled(False)
        self.start_button.setText("Стоп")
        self.pipeline.start(jobs, self.settings)

    def _on_item_done(self, index: int, result) -> None:
        self.model.set_result(index, result)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.summary_label.setText(f"Обработано {done} из {total}")

    def _on_finished(self, summary: Summary) -> None:
        self.panel.set_busy(False)
        self.drop_zone.setEnabled(True)
        self.start_button.setEnabled(True)
        self.start_button.setText("Сжать")
        self.progress.setVisible(False)
        for button in (
            self.remove_button, self.clear_button,
            self.check_all_button, self.uncheck_all_button, self.preview_button,
        ):
            button.setEnabled(True)

        if summary.cancelled:
            self.summary_label.setText(
                f"Остановлено · успели {summary.processed} из {summary.total}"
            )
            self._refresh_path_link()
            return

        saved = max(0, summary.source_bytes - summary.output_bytes)
        percent = 100 * saved / summary.source_bytes if summary.source_bytes else 0
        details = [f"файлов {summary.total}", f"экономия {percent:.0f}%"]
        if summary.too_big:
            details.append(f"не влезли: {summary.too_big}")
        if summary.skipped:
            details.append(f"пропущено: {summary.skipped}")
        if summary.errors:
            details.append(f"ошибок: {summary.errors}")
        self.summary_label.setText(
            f"Готово · {human_size(summary.source_bytes)} → "
            f"{human_size(summary.output_bytes)} · {' · '.join(details)}"
        )
        self._refresh_path_link()

    # ------------------------------------------------------------------
    def _refresh_path_link(self) -> None:
        if self.settings.output_dir:
            self.path_link.setText(f"→  {self.settings.output_dir}")
            self.path_link.setToolTip("Открыть папку с результатами")
        else:
            self.path_link.setText("→  Выбрать папку для результатов")
            self.path_link.setToolTip("Папка ещё не выбрана")

    def _refresh_summary(self) -> None:
        count = len(self.model.rows)
        checked = self.model.checked_count()
        busy = self.pipeline.running

        for button in (self.remove_button, self.clear_button):
            button.setEnabled(count > 0 and not busy)
        for button in (self.check_all_button, self.uncheck_all_button, self.preview_button):
            button.setEnabled(count > 0 and not busy)
        self.start_button.setEnabled(checked > 0)
        self._refresh_path_link()

        if not count:
            self.drop_zone.set_compact(False)
            self.list_label.setText("Список пуст")
            self.summary_label.setText("Перетащите фотографии или папки")
            return

        self.drop_zone.set_compact(True)
        marked = f"отмечено {checked} из {count}" if checked != count else f"{count} {_plural(count)}"
        self.list_label.setText(f"{marked} · {human_size(self.model.checked_size())}")
        self.summary_label.setText(
            f"{marked} · {human_size(self.model.checked_size())}"
        )

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
