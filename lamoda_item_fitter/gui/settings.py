"""Настройки: то, что редко трогают, спрятано за шестерёнкой."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __author__, __handle__, __version__
from ..batch import COPY, OVERWRITE, SKIP
from ..config import Preset

CONFLICT_LABELS = [
    ("Сохранить копией", COPY),
    ("Перезаписать", OVERWRITE),
    ("Пропустить", SKIP),
]
CROPPED_LABELS = [
    ("Переносить без подгонки", "passthrough"),
    ("Пропускать", "skip"),
    ("Вписывать по видимой части", "fit"),
]
SHADOW_LABELS = [
    ("Не включать в габарит", "exclude"),
    ("Включать в габарит", "include"),
]


class SettingsDialog(QDialog):
    def __init__(self, preset: Preset, output_root: Path | None, conflict: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(460)
        self._preset = preset

        self.format_box = QComboBox()
        self.format_box.addItems(["JPEG", "PNG"])
        self.format_box.setCurrentIndex(0 if preset.output.format.lower() != "png" else 1)

        self.quality = QSpinBox()
        self.quality.setRange(60, 100)
        self.quality.setValue(preset.output.jpeg_quality)

        self.suffix = QLineEdit(preset.output.suffix)
        self.folder_suffix = QCheckBox("Добавлять суффикс и к имени папки")
        self.folder_suffix.setChecked(preset.output.suffix_on_folder)

        self.conflict = QComboBox()
        for title, _ in CONFLICT_LABELS:
            self.conflict.addItem(title)
        self.conflict.setCurrentIndex(
            next(i for i, (_, value) in enumerate(CONFLICT_LABELS) if value == conflict))

        self.cropped = QComboBox()
        for title, _ in CROPPED_LABELS:
            self.cropped.addItem(title)
        self.cropped.setCurrentIndex(
            next(i for i, (_, value) in enumerate(CROPPED_LABELS)
                 if value == preset.cropped_policy))

        self.shadow = QComboBox()
        for title, _ in SHADOW_LABELS:
            self.shadow.addItem(title)
        self.shadow.setCurrentIndex(
            next(i for i, (_, value) in enumerate(SHADOW_LABELS) if value == preset.shadow_mode))

        self.output = QLineEdit(str(output_root) if output_root else "")
        self.output.setPlaceholderText("по умолчанию — папка «Загрузки»")
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self._pick_folder)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output)
        output_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("Формат", self.format_box)
        form.addRow("Качество JPEG", self.quality)
        form.addRow("Суффикс файлов", self.suffix)
        form.addRow("", self.folder_suffix)
        form.addRow("Если файл уже есть", self.conflict)
        form.addRow("Макро-кадры", self.cropped)
        form.addRow("Тень под товаром", self.shadow)
        form.addRow("Папка результата", output_row)

        note = QLabel("Правила холста и отступов заданы пресетом presets/lamoda.json "
                      "и выверены по фото, прошедшим модерацию.")
        note.setObjectName("hint")
        note.setWordWrap(True)

        product = QLabel(f"{APP_NAME} {__version__}")
        product.setObjectName("creditProduct")
        product.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        credit = QLabel(f"Разработка — {__author__} · {__handle__}")
        credit.setObjectName("credit")
        credit.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        # две строки подписи держим вплотную: иначе растяжка окна разгоняет их
        # по вертикали и блок перестаёт читаться как единое целое
        signature = QVBoxLayout()
        signature.setSpacing(1)
        signature.setContentsMargins(0, 0, 0, 0)
        signature.addWidget(product)
        signature.addWidget(credit)
        signature_box = QWidget()
        signature_box.setLayout(signature)

        layout.addWidget(buttons)
        layout.addStretch(1)
        layout.addSpacing(4)
        layout.addWidget(signature_box)

    def _pick_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Куда сохранять результат")
        if chosen:
            self.output.setText(chosen)

    def result_preset(self) -> Preset:
        output = self._preset.output
        updated = output.__class__(**{
            **output.__dict__,
            "format": "png" if self.format_box.currentIndex() == 1 else "jpeg",
            "jpeg_quality": self.quality.value(),
            "suffix": self.suffix.text().strip() or output.suffix,
            "suffix_on_folder": self.folder_suffix.isChecked(),
        })
        return self._preset.replace(
            output=updated,
            cropped_policy=CROPPED_LABELS[self.cropped.currentIndex()][1],
            shadow_mode=SHADOW_LABELS[self.shadow.currentIndex()][1],
        )

    def result_conflict(self) -> str:
        return CONFLICT_LABELS[self.conflict.currentIndex()][1]

    def result_output(self) -> Path | None:
        text = self.output.text().strip()
        return Path(text) if text else None
