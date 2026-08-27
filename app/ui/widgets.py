"""Мелкие переиспользуемые кусочки интерфейса."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QDoubleSpinBox,
    QSpinBox,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)


class MegabyteSpinBox(QDoubleSpinBox):
    """Счётчик мегабайт без хвостовых нулей: 5 МБ, 2.5 МБ, 0.35 МБ."""

    def textFromValue(self, value: float) -> str:  # noqa: N802 - как у Qt
        return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


class Card(QFrame):
    """Панель со скруглением — базовый строительный блок правой колонки."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 10):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 16)
        self.body.setSpacing(spacing)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)


def section_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("sectionTitle")
    return label


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def separator() -> QFrame:
    line = QFrame()
    line.setObjectName("separator")
    line.setFrameShape(QFrame.HLine)
    line.setFixedHeight(1)
    return line


class SliderRow(QWidget):
    """Подпись, ползунок и числовое поле, синхронизированные между собой."""

    valueChanged = Signal(int)

    def __init__(
        self,
        label: str,
        minimum: int,
        maximum: int,
        value: int,
        suffix: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(label)
        self.label.setObjectName("fieldLabel")
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setValue(value)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(84)
        self.spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.label)
        top.addStretch(1)
        top.addWidget(self.spin)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)

        layout.addLayout(top)
        layout.addWidget(self.slider)

        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def _from_slider(self, value: int) -> None:
        if self.spin.value() != value:
            self.spin.blockSignals(True)
            self.spin.setValue(value)
            self.spin.blockSignals(False)
        self.valueChanged.emit(value)

    def _from_spin(self, value: int) -> None:
        if self.slider.value() != value:
            self.slider.blockSignals(True)
            self.slider.setValue(value)
            self.slider.blockSignals(False)
        self.valueChanged.emit(value)

    def value(self) -> int:
        return self.spin.value()

    def setValue(self, value: int) -> None:  # noqa: N802 - как у Qt
        self.slider.setValue(value)
        self.spin.setValue(value)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - как у Qt
        super().setEnabled(enabled)
        self.label.setEnabled(enabled)


class DropZone(QFrame):
    """Область, куда бросают файлы и папки.

    Два готовых вида вместо пересборки раскладки: просторный, пока список
    пуст, и узкая полоска, когда файлы уже добавлены и место нужнее списку.
    """

    dropped = Signal(list)
    browse_files = Signal()
    browse_folder = Signal()

    FULL_HEIGHT = 118
    COMPACT_HEIGHT = 62

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setProperty("hover", "false")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._build_full())
        self._stack.addWidget(self._build_compact())
        self.set_compact(False)

    def _buttons(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)
        for text, signal in (
            ("Выбрать файлы", self.browse_files),
            ("Выбрать папку", self.browse_folder),
        ):
            button = QPushButton(text)
            button.clicked.connect(signal)
            layout.addWidget(button)
        return layout

    def _build_full(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(3)
        layout.setAlignment(Qt.AlignCenter)

        title = QLabel("Перетащите сюда фотографии или папки")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignCenter)

        subtitle = QLabel("Вложенные папки разбираются целиком")
        subtitle.setObjectName("dropHint")
        subtitle.setAlignment(Qt.AlignCenter)

        buttons = self._buttons()
        buttons.setAlignment(Qt.AlignCenter)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addLayout(buttons)
        return page

    def _build_compact(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(12)

        title = QLabel("Перетащите фото или папки")
        title.setObjectName("dropTitle")
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addLayout(self._buttons())
        return page

    def set_compact(self, compact: bool) -> None:
        self._stack.setCurrentIndex(1 if compact else 0)
        self.setFixedHeight(self.COMPACT_HEIGHT if compact else self.FULL_HEIGHT)

    # --- перетаскивание ---------------------------------------------------
    def _set_hover(self, hovering: bool) -> None:
        self.setProperty("hover", "true" if hovering else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_hover(True)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._set_hover(False)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._set_hover(False)
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self.dropped.emit(paths)
            event.acceptProposedAction()


def human_size(size: int) -> str:
    """Человеческий вес файла: 1.4 МБ, 812 КБ."""
    if size <= 0:
        return "—"
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} КБ"
    megabytes = size / 1024 / 1024
    # Сотые доли мегабайта ничего не решают, зато занимают место в колонке.
    return f"{megabytes:.1f} МБ".replace(".0 МБ", " МБ")
