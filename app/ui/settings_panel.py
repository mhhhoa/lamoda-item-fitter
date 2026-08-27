"""Правая колонка: все параметры обработки."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.settings import (
    CONFLICT_OVERWRITE,
    CONFLICT_SKIP,
    CONFLICT_SUFFIX,
    MODE_LOSSLESS,
    MODE_MANUAL,
    MODE_SMART,
    OUTPUT_FORMATS,
    Settings,
)
from .widgets import Card, MegabyteSpinBox, SliderRow, hint, section_title

MODE_HINTS = {
    MODE_LOSSLESS: "Пиксели не меняются вообще. Экономия 5–15%, "
                   "в жёсткий лимит попадает не всегда.",
    MODE_SMART: "Держит качество настолько высоким, насколько позволяет лимит: "
                "сначала пробует без потерь, потом снижает качество, и лишь в "
                "крайнем случае уменьшает картинку.",
    MODE_MANUAL: "Просто применяет заданное качество и размер, ни под что не подстраиваясь.",
}

SIZE_PRESETS = [("Ламода · 5 МБ", 5.0), ("2 МБ", 2.0), ("1 МБ", 1.0)]
SIDE_PRESETS = [1600, 2000, 2400, 3000]


class SettingsPanel(QWidget):
    """Собирает Settings из виджетов и сообщает наверх о любых изменениях."""

    changed = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings = settings
        self._building = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._build_size_card())
        layout.addWidget(self._build_quality_card())
        layout.addWidget(self._build_resolution_card())
        layout.addWidget(self._build_format_card())
        layout.addWidget(self._build_output_card())
        layout.addStretch(1)

        self._building = False
        self._sync_enabled()

    # ------------------------------------------------------------------
    # Карточки
    # ------------------------------------------------------------------
    def _build_size_card(self) -> Card:
        card = Card()
        card.add(section_title("Целевой вес"))

        row = QHBoxLayout()
        row.setSpacing(8)
        self.limit_check = QCheckBox("Не тяжелее")
        self.limit_check.setChecked(self._settings.limit_enabled)
        self.limit_spin = MegabyteSpinBox()
        self.limit_spin.setRange(0.05, 200.0)
        self.limit_spin.setDecimals(2)
        self.limit_spin.setSingleStep(0.5)
        self.limit_spin.setSuffix(" МБ")
        self.limit_spin.setValue(self._settings.target_mb)
        self.limit_spin.setFixedWidth(110)
        row.addWidget(self.limit_check)
        row.addStretch(1)
        row.addWidget(self.limit_spin)
        card.add_layout(row)

        presets = QHBoxLayout()
        presets.setSpacing(6)
        for label, value in SIZE_PRESETS:
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, v=value: self.limit_spin.setValue(v))
            presets.addWidget(button)
        presets.addStretch(1)
        card.add_layout(presets)

        card.add(hint("Ламода не принимает файлы тяжелее 5 МБ. Программа целится "
                      "чуть ниже лимита, чтобы округления на стороне площадки не подвели."))

        self.limit_check.toggled.connect(self._on_change)
        self.limit_spin.valueChanged.connect(self._on_change)
        return card

    def _build_quality_card(self) -> Card:
        card = Card()
        card.add(section_title("Качество"))

        self.mode_group = QButtonGroup(self)
        modes = QHBoxLayout()
        modes.setSpacing(14)
        self.mode_buttons: dict[str, QRadioButton] = {}
        for key, label in (
            (MODE_LOSSLESS, "Без потерь"),
            (MODE_SMART, "Умный"),
            (MODE_MANUAL, "Ручной"),
        ):
            button = QRadioButton(label)
            button.setChecked(self._settings.mode == key)
            self.mode_group.addButton(button)
            self.mode_buttons[key] = button
            modes.addWidget(button)
        modes.addStretch(1)
        card.add_layout(modes)

        self.mode_hint = hint(MODE_HINTS[self._settings.mode])
        card.add(self.mode_hint)

        self.quality_row = SliderRow("Качество", 40, 100, self._settings.quality)
        self.min_quality_row = SliderRow("Не опускать ниже", 30, 100, self._settings.min_quality)
        card.add(self.quality_row)
        card.add(self.min_quality_row)

        for button in self.mode_buttons.values():
            button.toggled.connect(self._on_change)
        self.quality_row.valueChanged.connect(self._on_quality_change)
        self.min_quality_row.valueChanged.connect(self._on_quality_change)
        return card

    def _build_resolution_card(self) -> Card:
        card = Card()
        card.add(section_title("Разрешение"))

        row = QHBoxLayout()
        row.setSpacing(8)
        self.max_side_check = QCheckBox("Длинная сторона не больше")
        self.max_side_check.setChecked(self._settings.max_side_enabled)
        self.max_side_spin = QSpinBox()
        self.max_side_spin.setRange(64, 20000)
        self.max_side_spin.setSingleStep(100)
        self.max_side_spin.setSuffix(" px")
        self.max_side_spin.setValue(self._settings.max_side)
        self.max_side_spin.setFixedWidth(110)
        row.addWidget(self.max_side_check)
        row.addStretch(1)
        row.addWidget(self.max_side_spin)
        card.add_layout(row)

        presets = QHBoxLayout()
        presets.setSpacing(6)
        for value in SIDE_PRESETS:
            button = QPushButton(f"{value}")
            button.clicked.connect(lambda _=False, v=value: self.max_side_spin.setValue(v))
            presets.addWidget(button)
        presets.addStretch(1)
        card.add_layout(presets)

        self.downscale_check = QCheckBox("Уменьшать сильнее, если иначе не влезает")
        self.downscale_check.setChecked(self._settings.allow_downscale)
        card.add(self.downscale_check)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.min_side_check = QCheckBox("Но не меньше")
        self.min_side_check.setChecked(self._settings.min_side_enabled)
        self.min_side_spin = QSpinBox()
        self.min_side_spin.setRange(16, 20000)
        self.min_side_spin.setSingleStep(100)
        self.min_side_spin.setSuffix(" px")
        self.min_side_spin.setValue(self._settings.min_side)
        self.min_side_spin.setFixedWidth(110)
        row.addWidget(self.min_side_check)
        row.addStretch(1)
        row.addWidget(self.min_side_spin)
        card.add_layout(row)

        card.add(hint("Уменьшение — самый безобидный способ снять вес: "
                      "детали теряются куда мягче, чем при низком качестве."))

        for widget in (self.max_side_check, self.downscale_check, self.min_side_check):
            widget.toggled.connect(self._on_change)
        self.max_side_spin.valueChanged.connect(self._on_change)
        self.min_side_spin.valueChanged.connect(self._on_change)
        return card

    def _build_format_card(self) -> Card:
        card = Card()
        card.add(section_title("Формат"))

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("Сохранять как")
        label.setObjectName("fieldLabel")
        self.format_combo = QComboBox()
        for key, (title, _) in OUTPUT_FORMATS.items():
            self.format_combo.addItem(title, key)
        index = self.format_combo.findData(self._settings.output_format)
        self.format_combo.setCurrentIndex(max(0, index))
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(self.format_combo, 1)
        card.add_layout(row)

        self.metadata_check = QCheckBox("Сохранять метаданные (дата, камера, геометка)")
        self.metadata_check.setChecked(self._settings.keep_metadata)
        card.add(self.metadata_check)

        self.advanced_toggle = QPushButton("▸  Дополнительно")
        self.advanced_toggle.setObjectName("link")
        self.advanced_toggle.setCursor(Qt.PointingHandCursor)
        card.add(self.advanced_toggle)

        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 2, 0, 0)
        advanced_layout.setSpacing(8)

        self.srgb_check = QCheckBox("Приводить цвета к sRGB")
        self.srgb_check.setChecked(self._settings.convert_to_srgb)
        self.srgb_check.setToolTip(
            "Снимки в Adobe RGB на сайте выглядят блёкло — площадка не читает профиль."
        )
        self.progressive_check = QCheckBox("Прогрессивный JPEG")
        self.progressive_check.setChecked(self._settings.progressive)
        self.progressive_check.setToolTip("Чуть меньше вес и плавная загрузка в браузере.")
        advanced_layout.addWidget(self.srgb_check)
        advanced_layout.addWidget(self.progressive_check)

        sub_row = QHBoxLayout()
        sub_label = QLabel("Цветовые каналы")
        sub_label.setObjectName("fieldLabel")
        self.subsampling_combo = QComboBox()
        for key, title in (
            ("auto", "Авто"), ("444", "4:4:4 — максимум цвета"),
            ("422", "4:2:2"), ("420", "4:2:0 — минимум веса"),
        ):
            self.subsampling_combo.addItem(title, key)
        self.subsampling_combo.setCurrentIndex(
            max(0, self.subsampling_combo.findData(self._settings.subsampling))
        )
        sub_row.addWidget(sub_label)
        sub_row.addStretch(1)
        sub_row.addWidget(self.subsampling_combo, 1)
        advanced_layout.addLayout(sub_row)

        threads_row = QHBoxLayout()
        threads_label = QLabel("Потоков обработки")
        threads_label.setObjectName("fieldLabel")
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 32)
        self.threads_spin.setSpecialValueText("Авто")
        self.threads_spin.setValue(self._settings.threads)
        self.threads_spin.setFixedWidth(110)
        threads_row.addWidget(threads_label)
        threads_row.addStretch(1)
        threads_row.addWidget(self.threads_spin)
        advanced_layout.addLayout(threads_row)

        self.advanced.setVisible(False)
        card.add(self.advanced)

        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        self.format_combo.currentIndexChanged.connect(self._on_change)
        self.subsampling_combo.currentIndexChanged.connect(self._on_change)
        for widget in (self.metadata_check, self.srgb_check, self.progressive_check):
            widget.toggled.connect(self._on_change)
        self.threads_spin.valueChanged.connect(self._on_change)
        return card

    def _build_output_card(self) -> Card:
        card = Card()
        card.add(section_title("Куда сохранять"))

        row = QHBoxLayout()
        row.setSpacing(8)
        self.output_field = QLineEdit(self._settings.output_dir)
        self.output_field.setObjectName("pathField")
        self.output_field.setPlaceholderText("Папка не выбрана")
        self.output_field.setReadOnly(True)
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self._choose_output)
        row.addWidget(self.output_field, 1)
        row.addWidget(browse)
        card.add_layout(row)

        self.structure_group = QButtonGroup(self)
        self.keep_structure_radio = QRadioButton("Повторить структуру папок")
        self.flat_radio = QRadioButton("Всё одной кучей в выбранную папку")
        self.keep_structure_radio.setChecked(self._settings.keep_structure)
        self.flat_radio.setChecked(not self._settings.keep_structure)
        self.structure_group.addButton(self.keep_structure_radio)
        self.structure_group.addButton(self.flat_radio)
        card.add(self.keep_structure_radio)
        card.add(self.flat_radio)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("Если имя занято")
        label.setObjectName("fieldLabel")
        self.conflict_combo = QComboBox()
        for key, title in (
            (CONFLICT_SUFFIX, "Добавить номер"),
            (CONFLICT_OVERWRITE, "Перезаписать"),
            (CONFLICT_SKIP, "Пропустить файл"),
        ):
            self.conflict_combo.addItem(title, key)
        self.conflict_combo.setCurrentIndex(
            max(0, self.conflict_combo.findData(self._settings.on_conflict))
        )
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(self.conflict_combo, 1)
        card.add_layout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("Суффикс к имени")
        label.setObjectName("fieldLabel")
        self.suffix_field = QLineEdit(self._settings.name_suffix)
        self.suffix_field.setPlaceholderText("необязательно, например _lamoda")
        row.addWidget(label)
        row.addWidget(self.suffix_field, 1)
        card.add_layout(row)

        self.copy_small_check = QCheckBox("Подходящие файлы копировать без изменений")
        self.copy_small_check.setChecked(self._settings.copy_when_already_small)
        card.add(self.copy_small_check)

        self.keep_structure_radio.toggled.connect(self._on_change)
        self.conflict_combo.currentIndexChanged.connect(self._on_change)
        self.suffix_field.textChanged.connect(self._on_change)
        self.copy_small_check.toggled.connect(self._on_change)
        return card

    # ------------------------------------------------------------------
    # Поведение
    # ------------------------------------------------------------------
    def _toggle_advanced(self) -> None:
        visible = not self.advanced.isVisible()
        self.advanced.setVisible(visible)
        self.advanced_toggle.setText(("▾  " if visible else "▸  ") + "Дополнительно")

    def _choose_output(self) -> None:
        start = self._settings.output_dir or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Куда складывать результат", start)
        if chosen:
            self.output_field.setText(chosen)
            self._on_change()

    def _on_quality_change(self, _value: int) -> None:
        # Нижняя граница не должна перепрыгивать верхнюю.
        if self.min_quality_row.value() > self.quality_row.value():
            self.min_quality_row.setValue(self.quality_row.value())
        self._on_change()

    def _on_change(self, *_args) -> None:
        if self._building:
            return
        self._sync_enabled()
        self.changed.emit()

    def _sync_enabled(self) -> None:
        mode = self.current_mode()
        self.mode_hint.setText(MODE_HINTS[mode])

        lossy_format = self.format_combo.currentData() != "png"
        self.quality_row.setEnabled(mode != MODE_LOSSLESS and lossy_format)
        self.min_quality_row.setEnabled(mode == MODE_SMART and lossy_format)
        self.quality_row.label.setText(
            "Верхняя планка качества" if mode == MODE_SMART else "Качество"
        )

        limited = self.limit_check.isChecked()
        self.limit_spin.setEnabled(limited)
        self.downscale_check.setEnabled(limited and mode == MODE_SMART)
        self.copy_small_check.setEnabled(limited)

        downscaling = self.downscale_check.isEnabled() and self.downscale_check.isChecked()
        self.min_side_check.setEnabled(downscaling)
        self.min_side_spin.setEnabled(downscaling and self.min_side_check.isChecked())
        self.max_side_spin.setEnabled(self.max_side_check.isChecked())

    def current_mode(self) -> str:
        for key, button in self.mode_buttons.items():
            if button.isChecked():
                return key
        return MODE_SMART

    # ------------------------------------------------------------------
    def collect(self) -> Settings:
        """Снимает текущее состояние всех виджетов в объект настроек."""
        settings = self._settings
        settings.limit_enabled = self.limit_check.isChecked()
        settings.target_mb = self.limit_spin.value()
        settings.mode = self.current_mode()
        settings.quality = self.quality_row.value()
        settings.min_quality = self.min_quality_row.value()
        settings.max_side_enabled = self.max_side_check.isChecked()
        settings.max_side = self.max_side_spin.value()
        settings.min_side_enabled = self.min_side_check.isChecked()
        settings.min_side = self.min_side_spin.value()
        settings.allow_downscale = self.downscale_check.isChecked()
        settings.output_format = self.format_combo.currentData()
        settings.keep_metadata = self.metadata_check.isChecked()
        settings.convert_to_srgb = self.srgb_check.isChecked()
        settings.progressive = self.progressive_check.isChecked()
        settings.subsampling = self.subsampling_combo.currentData()
        settings.threads = self.threads_spin.value()
        settings.output_dir = self.output_field.text().strip()
        settings.keep_structure = self.keep_structure_radio.isChecked()
        settings.on_conflict = self.conflict_combo.currentData()
        settings.name_suffix = self.suffix_field.text().strip()
        settings.copy_when_already_small = self.copy_small_check.isChecked()
        return settings.normalized()

    def set_busy(self, busy: bool) -> None:
        self.setEnabled(not busy)
