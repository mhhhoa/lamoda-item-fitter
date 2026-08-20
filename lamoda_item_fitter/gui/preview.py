"""Превью «до/после» с направляющими отступов.

Нетехническому коллеге проще один раз увидеть, что товар стоит на линии,
чем поверить числам в отчёте.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import errors
from ..config import Preset
from .theme import Palette


class PreviewView(QWidget):
    """Показывает результат с рамкой полей и линией нижнего отступа."""

    def __init__(self, preset: Preset, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preset = preset
        self._palette = palette
        self._before: QImage | None = None
        self._after: QImage | None = None
        self._show_before = False
        self._caption = "Выберите файл в списке, чтобы увидеть результат"
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_images(self, before: QImage | None, after: QImage | None, caption: str = "") -> None:
        self._before, self._after = before, after
        self._caption = caption
        self.update()

    def clear(self) -> None:
        self.set_images(None, None, "Выберите файл в списке, чтобы увидеть результат")

    def show_before(self, enabled: bool) -> None:
        self._show_before = enabled
        self.update()

    @property
    def has_before(self) -> bool:
        return self._before is not None

    def _active(self) -> QImage | None:
        if self._show_before and self._before is not None:
            return self._before
        return self._after or self._before

    @errors.guard("отрисовка превью")
    def paintEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        painter = QPainter(self)
        try:
            self._paint(painter)
        finally:
            # painter обязан закрыться до выхода из обработчика, иначе Qt
            # ругается на активный painter в бэкстор
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(self._palette.surface_alt))

        image = self._active()
        if image is None or image.isNull():
            painter.setPen(QColor(self._palette.muted))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._caption)
            return

        margin = 14
        area = self.rect().adjusted(margin, margin, -margin, -margin - 22)
        scale = min(area.width() / image.width(), area.height() / image.height())
        width = max(1, int(image.width() * scale))
        height = max(1, int(image.height() * scale))
        target = QRect(area.x() + (area.width() - width) // 2,
                       area.y() + (area.height() - height) // 2, width, height)
        painter.drawImage(target, image)
        painter.setPen(QPen(QColor(self._palette.border), 1))
        painter.drawRect(target)

        showing_result = not (self._show_before and self._before is not None)
        if showing_result and self._matches_canvas(image):
            self._draw_guides(painter, target)

        painter.setPen(QColor(self._palette.muted))
        painter.drawText(
            QRect(self.rect().x(), target.bottom() + 6, self.rect().width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            self._caption or ("исходник" if not showing_result else "результат"),
        )

    def _matches_canvas(self, image: QImage) -> bool:
        """Кадр уже приведён к холсту.

        Сравниваем пропорции, а не пиксели: для показа изображение читается
        сразу уменьшенным, и точный размер до сюда не доезжает.
        """
        if not image.height():
            return False
        expected = self._preset.canvas.width / self._preset.canvas.height
        return abs(image.width() / image.height() - expected) < 0.01

    def _draw_guides(self, painter: QPainter, target: QRect) -> None:
        preset = self._preset
        scale = target.width() / preset.canvas.width
        left = target.x() + preset.margins.left * scale
        right = target.x() + (preset.canvas.width - preset.margins.right) * scale
        top = target.y() + preset.margins.top * scale
        baseline = target.y() + preset.baseline_y * scale

        painter.setPen(QPen(QColor(220, 70, 70, 190), 1, Qt.PenStyle.DashLine))
        painter.drawRect(QRect(int(left), int(top), int(right - left), int(baseline - top)))
        painter.setPen(QPen(QColor(30, 170, 110), 2))
        painter.drawLine(target.x(), int(baseline), target.right(), int(baseline))
