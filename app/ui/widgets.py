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
    """Область, куда бросают файлы и папки."""

    dropped = Signal(list)
    browse_files = Signal()
    browse_folder = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setProperty("hover", "false")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(118)

        self._compact = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 14, 20, 14)
        self._layout.setSpacing(3)

        self.title = QLabel("Перетащите сюда фотографии или папки")
        self.title.setObjectName("dropTitle")
        self.subtitle = QLabel("Вложенные папки разбираются целиком")
        self.subtitle.setObjectName("dropHint")

        files_button = QPushButton("Выбрать файлы")
        folder_button = QPushButton("Выбрать папку")
        files_button.clicked.connect(self.browse_files)
        folder_button.clicked.connect(self.browse_folder)
        self._buttons = QHBoxLayout()
        self._buttons.setSpacing(8)
        self._buttons.addWidget(files_button)
        self._buttons.addWidget(folder_button)

        self._build_layout()

    def _build_layout(self) -> None:
        """Просторный вид для пустого списка, узкая полоска — когда файлы есть."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(self)
            elif item.layout() is not None:
                item.layout().setParent(None)

        if self._compact:
            self.setMinimumHeight(0)
            self.setFixedHeight(62)
            self.subtitle.setVisible(False)
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(self.title)
            row.addStretch(1)
            row.addLayout(self._buttons)
            self._layout.addLayout(row)
            self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        else:
            self.setMinimumHeight(118)
            self.setMaximumHeight(16777215)
            self.subtitle.setVisible(True)
            self._layout.setAlignment(Qt.AlignCenter)
            self.title.setAlignment(Qt.AlignCenter)
            self.subtitle.setAlignment(Qt.AlignCenter)
            self._buttons.setAlignment(Qt.AlignCenter)
            self._layout.addWidget(self.title)
            self._layout.addWidget(self.subtitle)
            self._layout.addSpacing(8)
            self._layout.addLayout(self._buttons)

    def set_compact(self, compact: bool) -> None:
        if compact != self._compact:
            self._compact = compact
            self._build_layout()

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
    return f"{size / 1024 / 1024:.2f} МБ".replace(".00 МБ", " МБ")
