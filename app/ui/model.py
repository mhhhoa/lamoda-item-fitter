"""Модель списка файлов и фоновая подгрузка миниатюр."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap

from ..core.compressor import Result, Status
from ..core.jobs import Job
from .theme import COLORS
from .widgets import human_size

THUMB_SIZE = 40

COLUMNS = ["", "Файл", "Папка", "Было", "Стало", "Экономия", "Статус"]

STATUS_LABELS = {
    Status.OK: "Готово",
    Status.LOSSLESS: "Без потерь",
    Status.COPIED: "Скопирован",
    Status.NOT_LOSSLESS: "Без потерь не вышло",
    Status.TOO_BIG: "Не влез в лимит",
    Status.SKIPPED: "Пропущен",
    Status.ERROR: "Ошибка",
}

STATUS_COLORS = {
    Status.OK: COLORS["success"],
    Status.LOSSLESS: COLORS["success"],
    Status.COPIED: COLORS["text_muted"],
    Status.NOT_LOSSLESS: COLORS["warning"],
    Status.TOO_BIG: COLORS["warning"],
    Status.SKIPPED: COLORS["text_faint"],
    Status.ERROR: COLORS["danger"],
}


@dataclass
class Row:
    job: Job
    size: int = 0
    result: Result | None = None
    icon: QIcon | None = None
    thumb_requested: bool = False


# ---------------------------------------------------------------------------
# Миниатюры
# ---------------------------------------------------------------------------

class _ThumbSignals(QObject):
    ready = Signal(int, object)


class _ThumbTask(QRunnable):
    def __init__(self, row: int, path: Path, signals: _ThumbSignals):
        super().__init__()
        self.row = row
        self.path = path
        self.signals = signals

    def run(self) -> None:  # noqa: D102
        image = self._render()
        self.signals.ready.emit(self.row, image)

    def _render(self) -> QImage | None:
        box = THUMB_SIZE * 2  # запас под экраны с высокой плотностью
        try:
            with Image.open(self.path) as source:
                # draft просит декодер сразу выдать уменьшенную картинку —
                # для JPEG это в разы быстрее полного разбора.
                source.draft("RGB", (box, box))
                image = ImageOps.exif_transpose(source) or source
                image = image.convert("RGBA")
                image.thumbnail((box, box), Image.BILINEAR)
                data = image.tobytes("raw", "RGBA")
                return QImage(
                    data, image.width, image.height,
                    image.width * 4, QImage.Format_RGBA8888,
                ).copy()
        except Exception:
            return None


class ThumbnailLoader(QObject):
    """Готовит миниатюры в фоне, не мешая прокрутке списка."""

    ready = Signal(int, object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        # Двух потоков хватает: превью нужны только для видимых строк.
        self._pool.setMaxThreadCount(2)
        self._signals = _ThumbSignals()
        self._signals.ready.connect(self.ready)

    def request(self, row: int, path: Path) -> None:
        self._pool.start(_ThumbTask(row, path, self._signals))

    def clear(self) -> None:
        """Снимает очередь превью и дожидается тех, что уже в работе."""
        self._pool.clear()
        self._pool.waitForDone(2000)


# ---------------------------------------------------------------------------
# Модель таблицы
# ---------------------------------------------------------------------------

class FileTableModel(QAbstractTableModel):
    COL_THUMB, COL_NAME, COL_FOLDER, COL_BEFORE, COL_AFTER, COL_SAVED, COL_STATUS = range(7)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.rows: list[Row] = []
        self._loader = ThumbnailLoader(self)
        self._loader.ready.connect(self._on_thumb)

    # --- обязательное для Qt ---------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # noqa: N802
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return COLUMNS[section]
        if role == Qt.TextAlignmentRole:
            if section in (self.COL_BEFORE, self.COL_AFTER, self.COL_SAVED):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        column = index.column()

        if role == Qt.DecorationRole and column == self.COL_THUMB:
            if row.icon is None and not row.thumb_requested:
                row.thumb_requested = True
                self._loader.request(index.row(), row.job.source)
            return row.icon

        if role == Qt.DisplayRole:
            return self._text(row, column)

        if role == Qt.ForegroundRole:
            if column == self.COL_STATUS and row.result is not None:
                return QColor(STATUS_COLORS[row.result.status])
            if column in (self.COL_FOLDER, self.COL_BEFORE):
                return QColor(COLORS["text_muted"])
            if column == self.COL_SAVED and row.result is not None:
                return QColor(
                    COLORS["success"] if row.result.saved_bytes > 0 else COLORS["text_muted"]
                )
            return None

        if role == Qt.TextAlignmentRole and column in (
            self.COL_BEFORE, self.COL_AFTER, self.COL_SAVED
        ):
            return int(Qt.AlignRight | Qt.AlignVCenter)

        if role == Qt.ToolTipRole:
            return self._tooltip(row)

        if role == Qt.SizeHintRole:
            return QSize(0, THUMB_SIZE + 12)

        return None

    # --- содержимое ячеек -------------------------------------------------
    def _text(self, row: Row, column: int) -> str:
        if column == self.COL_NAME:
            return row.job.source.name
        if column == self.COL_FOLDER:
            return row.job.folder_label or "—"
        if column == self.COL_BEFORE:
            return human_size(row.size)
        if column == self.COL_AFTER:
            if row.result is None or row.result.status is Status.SKIPPED:
                return "—"
            return human_size(row.result.output_size)
        if column == self.COL_SAVED:
            if row.result is None or not row.size:
                return ""
            if row.result.status is Status.SKIPPED:
                return "—"
            percent = 100 * (1 - row.result.ratio)
            return f"−{percent:.0f}%" if percent >= 0.5 else "0%"
        if column == self.COL_STATUS:
            if row.result is None:
                return ""
            label = STATUS_LABELS[row.result.status]
            details = self._details(row.result)
            return f"{label} · {details}" if details else label
        return ""

    @staticmethod
    def _details(result: Result) -> str:
        if result.status is Status.ERROR:
            return result.message
        if result.status is Status.NOT_LOSSLESS:
            return result.message.replace("Точный lossless невозможен: ", "")
        parts = []
        if result.width and result.height:
            parts.append(f"{result.width}×{result.height}")
        if result.quality is not None:
            parts.append(f"q{result.quality}")
        return " · ".join(parts)

    def _tooltip(self, row: Row) -> str:
        lines = [str(row.job.source)]
        if row.result is not None:
            if row.result.destination:
                lines.append(f"→ {row.result.destination}")
            if row.result.message:
                lines.append(row.result.message)
        return "\n".join(lines)

    # --- изменение содержимого -------------------------------------------
    def add_jobs(self, jobs: list[Job]) -> int:
        existing = {row.job.source for row in self.rows}
        fresh = [job for job in jobs if job.source not in existing]
        if not fresh:
            return 0
        start = len(self.rows)
        self.beginInsertRows(QModelIndex(), start, start + len(fresh) - 1)
        for job in fresh:
            try:
                size = job.source.stat().st_size
            except OSError:
                size = 0
            self.rows.append(Row(job=job, size=size))
        self.endInsertRows()
        return len(fresh)

    def remove_rows(self, indexes: list[int]) -> None:
        for position in sorted(set(indexes), reverse=True):
            if 0 <= position < len(self.rows):
                self.beginRemoveRows(QModelIndex(), position, position)
                self.rows.pop(position)
                self.endRemoveRows()

    def clear(self) -> None:
        self.beginResetModel()
        self.rows.clear()
        self._loader.clear()
        self.endResetModel()

    def reset_results(self) -> None:
        for row in self.rows:
            row.result = None
        self._emit_changed(0, len(self.rows) - 1)

    def set_result(self, position: int, result: Result) -> None:
        if 0 <= position < len(self.rows):
            self.rows[position].result = result
            self._emit_changed(position, position)

    def _emit_changed(self, first: int, last: int) -> None:
        if first > last or not self.rows:
            return
        self.dataChanged.emit(
            self.index(first, 0),
            self.index(last, len(COLUMNS) - 1),
        )

    def _on_thumb(self, position: int, image: QImage | None) -> None:
        if not (0 <= position < len(self.rows)):
            return
        if image is not None and not image.isNull():
            pixmap = QPixmap.fromImage(image)
            self.rows[position].icon = QIcon(pixmap)
        self._emit_changed(position, position)

    # --- сводка -----------------------------------------------------------
    def total_size(self) -> int:
        return sum(row.size for row in self.rows)

    def jobs(self) -> list[Job]:
        return [row.job for row in self.rows]
