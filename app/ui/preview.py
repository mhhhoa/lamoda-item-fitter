"""Окно сравнения «до и после» с перетаскиваемой шторкой."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, QPoint, QRect, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.compressor import Status, compress_bytes
from ..core.settings import Settings
from .theme import palette
from .widgets import human_size

#: Больше этого предпросмотр не рисует — на экран всё равно не влезет,
#: а держать в памяти два кадра по 24 Мпикс незачем.
PREVIEW_LIMIT = 1400


def _to_qimage(image: Image.Image) -> QImage:
    converted = image.convert("RGBA")
    data = converted.tobytes("raw", "RGBA")
    return QImage(
        data, converted.width, converted.height, converted.width * 4, QImage.Format_RGBA8888
    ).copy()


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    """Гоняет один файл текущими настройками, не трогая диск."""

    def __init__(self, source: Path, settings: Settings, signals: _Signals):
        super().__init__()
        self.source = source
        self.settings = settings
        self.signals = signals

    def run(self) -> None:  # noqa: D102
        try:
            raw = self.source.read_bytes()
            result = compress_bytes(raw, self.settings)

            with Image.open(io.BytesIO(raw)) as opened:
                before = ImageOps.exif_transpose(opened) or opened
                before.thumbnail((PREVIEW_LIMIT, PREVIEW_LIMIT), Image.LANCZOS)
                before_image = _to_qimage(before)
                before_size = ImageOps.exif_transpose(opened).size if opened else before.size

            with Image.open(io.BytesIO(result.data)) as done:
                done.load()
                after = done.copy()
                after.thumbnail((PREVIEW_LIMIT, PREVIEW_LIMIT), Image.LANCZOS)
                after_image = _to_qimage(after)
        except Exception as error:  # noqa: BLE001 - окно должно сказать, а не упасть
            self.signals.failed.emit(str(error) or error.__class__.__name__)
            return

        self.signals.done.emit(
            {
                "before": before_image,
                "after": after_image,
                "before_bytes": len(raw),
                "before_size": before_size,
                "result": result,
            }
        )


class Curtain(QWidget):
    """Два кадра в одной рамке, разделённые перетаскиваемой шторкой."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.before: QPixmap | None = None
        self.after: QPixmap | None = None
        self._split = 0.5
        self._dragging = False
        self.setMinimumSize(520, 360)
        self.setCursor(Qt.SplitHCursor)
        self.setMouseTracking(True)

    def set_images(self, before: QImage, after: QImage) -> None:
        self.before = QPixmap.fromImage(before)
        self.after = QPixmap.fromImage(after)
        self.update()

    def _frame(self) -> QRect:
        """Общая рамка: обе картинки вписываются в неё целиком."""
        if self.before is None or self.after is None:
            return self.rect()
        widest = max(
            self.before.width() / self.before.height(),
            self.after.width() / self.after.height(),
        )
        area = self.rect().adjusted(1, 1, -1, -1)
        height = min(area.height(), int(area.width() / widest))
        width = int(height * widest)
        return QRect(
            area.left() + (area.width() - width) // 2,
            area.top() + (area.height() - height) // 2,
            width,
            height,
        )

    @staticmethod
    def _fit(pixmap: QPixmap, frame: QRect) -> QRect:
        scale = min(frame.width() / pixmap.width(), frame.height() / pixmap.height())
        width = max(1, int(pixmap.width() * scale))
        height = max(1, int(pixmap.height() * scale))
        return QRect(
            frame.left() + (frame.width() - width) // 2,
            frame.top() + (frame.height() - height) // 2,
            width,
            height,
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        colors = palette(self.property("theme") or "dark")
        painter.fillRect(self.rect(), QColor(colors["bg"]))
        if self.before is None or self.after is None:
            painter.setPen(QColor(colors["text_muted"]))
            painter.drawText(self.rect(), Qt.AlignCenter, "Считаю предпросмотр…")
            return

        frame = self._frame()
        painter.drawPixmap(self._fit(self.after, frame), self.after)

        divider = frame.left() + int(frame.width() * self._split)
        painter.save()
        painter.setClipRect(QRect(frame.left(), frame.top(), divider - frame.left(), frame.height()))
        painter.drawPixmap(self._fit(self.before, frame), self.before)
        painter.restore()

        painter.setPen(QPen(QColor(colors["accent"]), 2))
        painter.drawLine(divider, frame.top(), divider, frame.bottom())

        for text, x, align in (
            ("до", frame.left() + 10, Qt.AlignLeft),
            ("после", frame.right() - 60, Qt.AlignRight),
        ):
            box = QRect(x, frame.top() + 8, 50, 18)
            painter.fillRect(box, QColor(0, 0, 0, 140))
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(box, Qt.AlignCenter, text)

    def _move_split(self, position: QPoint) -> None:
        frame = self._frame()
        if frame.width() <= 0:
            return
        self._split = min(1.0, max(0.0, (position.x() - frame.left()) / frame.width()))
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._dragging = True
        self._move_split(event.position().toPoint())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            self._move_split(event.position().toPoint())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = False


class PreviewDialog(QDialog):
    """Показывает, что текущие настройки сделают с одним конкретным файлом."""

    def __init__(self, source: Path, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Предпросмотр — {source.name}")
        self.resize(900, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.curtain = Curtain()
        self.curtain.setProperty("theme", settings.theme)
        layout.addWidget(self.curtain, 1)

        self.caption = QLabel("Считаю…")
        self.caption.setObjectName("summary")
        self.caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.caption)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Закрыть")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self._signals = _Signals()
        self._signals.done.connect(self._show_result)
        self._signals.failed.connect(self._show_error)
        QThreadPool.globalInstance().start(_Job(source, settings, self._signals))

    def _show_result(self, payload: dict) -> None:
        self.curtain.set_images(payload["before"], payload["after"])
        result = payload["result"]
        before_w, before_h = payload["before_size"]
        saved = 100 * (1 - len(result.data) / payload["before_bytes"]) if payload["before_bytes"] else 0
        quality = f" · качество {result.quality}" if result.quality is not None else ""
        warning = f"  ⚠ {result.note}" if result.note else ""
        limit = "" if result.status is not Status.TOO_BIG else "  ⚠ не влезает в лимит"
        self.caption.setText(
            f"{human_size(payload['before_bytes'])} · {before_w}×{before_h}"
            f"   →   {human_size(len(result.data))} · {result.width}×{result.height}"
            f"{quality} · −{saved:.0f}%{limit}{warning}"
        )

    def _show_error(self, message: str) -> None:
        self.caption.setText(f"Не получилось: {message}")
