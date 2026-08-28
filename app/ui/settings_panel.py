"""Правая колонка: все параметры обработки."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, AUTHOR, AUTHOR_HANDLE, VERSION_LABEL
from ..core.settings import (
    ANCHORS,
    ASPECT_BY_KEY,
    ASPECT_RATIOS,
    CONFLICT_OVERWRITE,
    CONFLICT_SKIP,
    CONFLICT_SUFFIX,
    FIT_MODES,
    MODE_LOSSLESS,
    MODE_MANUAL,
    MODE_SMART,
    OUTPUT_FORMATS,
    PAD_CUSTOM,
    PAD_MODES,
    SHARPEN_LEVELS,
    Profiles,
    Settings,
    reset_size_fields,
)
from .widgets import Card, MegabyteSpinBox, SliderRow, hint, section_title

MODE_HINTS = {
    MODE_LOSSLESS: "Пиксели не меняются вообще: ни качество, ни размер. "
                   "Экономия 5–15%, в жёсткий лимит попадает не всегда.",
    MODE_SMART: "Держит качество настолько высоким, насколько позволяет лимит: "
                "сначала пробует без потерь, потом снижает качество, и лишь в "
                "крайнем случае уменьшает картинку.",
    MODE_MANUAL: "Просто применяет заданное качество и размер, ни под что не подстраиваясь.",
}

SIZE_OFF = "off"
SIZE_LIMIT = "limit"
SIZE_EXACT = "exact"

SIDE_PRESETS = [1600, 2000, 2400, 3000]
SIZE_PRESETS = [("5 МБ", 5.0), ("2 МБ", 2.0), ("1 МБ", 1.0)]

RENAME_HELP = (
    "{name} — исходное имя, {folder} — папка, {n} — номер "
    "({n2}, {n3} — с нулями), {w} и {h} — размер результата"
)


class SettingsPanel(QWidget):
    """Собирает Settings из виджетов и сообщает наверх о любых изменениях."""

    changed = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings = settings
        self._profiles = Profiles()
        self._building = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._build_profile_card())
        layout.addWidget(self._build_weight_card())
        layout.addWidget(self._build_quality_card())
        layout.addWidget(self._build_size_card())
        layout.addWidget(self._build_format_card())
        layout.addWidget(self._build_output_card())
        layout.addStretch(1)
        layout.addWidget(self._build_credits())

        self._building = False
        self._sync_enabled()

    # ------------------------------------------------------------------
    # Профили
    # ------------------------------------------------------------------
    def _build_profile_card(self) -> Card:
        card = Card()
        card.add(section_title("Профиль"))

        row = QHBoxLayout()
        row.setSpacing(8)
        self.profile_combo = QComboBox()
        self._reload_profiles()
        save = QPushButton("Сохранить…")
        save.clicked.connect(self._save_profile)
        more = QPushButton("Ещё")
        more.clicked.connect(self._profile_menu)
        row.addWidget(self.profile_combo, 1)
        row.addWidget(save)
        row.addWidget(more)
        card.add_layout(row)

        card.add(hint("Набор настроек под имя. Файл профилей можно переслать "
                      "коллеге — и у всех будут одни и те же цифры."))
        self.profile_combo.activated.connect(self._apply_profile)
        return card

    def _reload_profiles(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("— без профиля —", "")
        for name in self._profiles.names():
            self.profile_combo.addItem(name, name)
        self.profile_combo.blockSignals(False)

    def _apply_profile(self, _index: int) -> None:
        name = self.profile_combo.currentData()
        if not name:
            return
        stored = self._profiles.get(name)
        if stored is None:
            return
        # Папка выгрузки и тема — про рабочее место, их профиль не трогает.
        stored.output_dir = self._settings.output_dir
        stored.theme = self._settings.theme
        self.load_from(stored)
        self.changed.emit()

    def _save_profile(self) -> None:
        current = self.profile_combo.currentData() or ""
        name, accepted = QInputDialog.getText(
            self, "Сохранить профиль", "Название профиля:", text=current
        )
        name = name.strip()
        if not accepted or not name:
            return
        self._profiles.put(name, self.collect())
        self._reload_profiles()
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(name)))

    def _profile_menu(self) -> None:
        menu = QMenu(self)
        name = self.profile_combo.currentData() or ""
        delete = menu.addAction("Удалить профиль")
        delete.setEnabled(bool(name))
        delete.triggered.connect(self._delete_profile)
        menu.addSeparator()
        menu.addAction("Экспорт в файл…").triggered.connect(self._export_profiles)
        menu.addAction("Импорт из файла…").triggered.connect(self._import_profiles)
        menu.exec(self.cursor().pos())

    def _delete_profile(self) -> None:
        name = self.profile_combo.currentData() or ""
        if not name:
            return
        answer = QMessageBox.question(self, "Удалить профиль", f"Удалить «{name}»?")
        if answer == QMessageBox.Yes:
            self._profiles.remove(name)
            self._reload_profiles()

    def _export_profiles(self) -> None:
        if not self._profiles.names():
            QMessageBox.information(self, "Пусто", "Пока нет ни одного профиля.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Куда сохранить профили", str(Path.home() / "imgfitter-профили.json"),
            "Профили (*.json)",
        )
        if path:
            self._profiles.export_to(Path(path))

    def _import_profiles(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Файл с профилями", str(Path.home()), "Профили (*.json)"
        )
        if not path:
            return
        try:
            added = self._profiles.import_from(Path(path))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Не получилось", f"Файл не прочитался:\n{error}")
            return
        self._reload_profiles()
        QMessageBox.information(self, "Готово", f"Добавлено профилей: {len(added)}")

    # ------------------------------------------------------------------
    # Вес
    # ------------------------------------------------------------------
    def _build_weight_card(self) -> Card:
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

        card.add(hint("Программа целится чуть ниже указанного, чтобы округления "
                      "на стороне площадки не подвели."))

        self.limit_check.toggled.connect(self._on_change)
        self.limit_spin.valueChanged.connect(self._on_change)
        return card

    # ------------------------------------------------------------------
    # Качество
    # ------------------------------------------------------------------
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

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("Резкость после уменьшения")
        label.setObjectName("fieldLabel")
        self.sharpen_combo = QComboBox()
        for key, title in SHARPEN_LEVELS.items():
            self.sharpen_combo.addItem(title, key)
        self.sharpen_combo.setCurrentIndex(
            max(0, self.sharpen_combo.findData(self._settings.sharpen))
        )
        self.sharpen_combo.setToolTip(
            "Уменьшение усредняет пиксели и мылит фактуру ткани. "
            "Аккуратный unsharp возвращает её."
        )
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(self.sharpen_combo)
        card.add_layout(row)

        for button in self.mode_buttons.values():
            button.toggled.connect(self._on_change)
        self.quality_row.valueChanged.connect(self._on_quality_change)
        self.min_quality_row.valueChanged.connect(self._on_quality_change)
        self.sharpen_combo.currentIndexChanged.connect(self._on_change)
        return card

    # ------------------------------------------------------------------
    # Размер
    # ------------------------------------------------------------------
    def _build_size_card(self) -> Card:
        card = self.size_card = Card()

        head = QHBoxLayout()
        head.addWidget(section_title("Размер"))
        head.addStretch(1)
        reset = QPushButton("Сброс")
        reset.setToolTip("Вернуть заводские значения размера")
        reset.clicked.connect(self._reset_size)
        head.addWidget(reset)
        card.add_layout(head)

        self.size_group = QButtonGroup(self)
        self.size_buttons: dict[str, QRadioButton] = {}
        for key, label in (
            (SIZE_OFF, "Не менять"),
            (SIZE_LIMIT, "Не больше по длинной стороне"),
            (SIZE_EXACT, "Точный размер"),
        ):
            button = QRadioButton(label)
            self.size_group.addButton(button)
            self.size_buttons[key] = button
            card.add(button)
            button.toggled.connect(self._on_change)
        self.size_buttons[self._size_mode_of(self._settings)].setChecked(True)

        card.add(self._build_limit_block())
        card.add(self._build_exact_block())
        return card

    def _build_limit_block(self) -> QWidget:
        block = self.limit_block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(22, 2, 0, 0)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("Длинная сторона")
        label.setObjectName("fieldLabel")
        self.max_side_spin = QSpinBox()
        self.max_side_spin.setRange(64, 20000)
        self.max_side_spin.setSingleStep(100)
        self.max_side_spin.setSuffix(" px")
        self.max_side_spin.setValue(self._settings.max_side)
        self.max_side_spin.setFixedWidth(110)
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(self.max_side_spin)
        layout.addLayout(row)

        presets = QHBoxLayout()
        presets.setSpacing(6)
        for value in SIDE_PRESETS:
            button = QPushButton(str(value))
            button.clicked.connect(lambda _=False, v=value: self.max_side_spin.setValue(v))
            presets.addWidget(button)
        presets.addStretch(1)
        layout.addLayout(presets)

        self.downscale_check = QCheckBox("Уменьшать сильнее, если иначе не влезает")
        self.downscale_check.setChecked(self._settings.allow_downscale)
        layout.addWidget(self.downscale_check)

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
        layout.addLayout(row)

        self.max_side_spin.valueChanged.connect(self._on_change)
        self.min_side_spin.valueChanged.connect(self._on_change)
        self.downscale_check.toggled.connect(self._on_change)
        self.min_side_check.toggled.connect(self._on_change)
        return block

    def _build_exact_block(self) -> QWidget:
        block = self.exact_block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(22, 2, 0, 0)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.width_spin = QSpinBox()
        self.height_spin = QSpinBox()
        for spin, value in (
            (self.width_spin, self._settings.exact_width),
            (self.height_spin, self._settings.exact_height),
        ):
            spin.setRange(1, 20000)
            spin.setSingleStep(50)
            spin.setSuffix(" px")
            spin.setValue(value)
            spin.setFixedWidth(96)
        self.link_button = QPushButton("↔")
        self.link_button.setObjectName("linkToggle")
        self.link_button.setCheckable(True)
        self.link_button.setChecked(self._settings.link_sides)
        self.link_button.setFixedSize(30, 30)
        self.link_button.setToolTip("Связать стороны: правишь одну — вторая пересчитается")
        self.link_button.toggled.connect(
            lambda on: self.link_button.setToolTip(
                "Стороны связаны — вторая идёт следом" if on
                else "Стороны независимы — обе цифры вводятся руками"
            )
        )
        row.addWidget(self.width_spin)
        row.addWidget(self.link_button)
        row.addWidget(self.height_spin)
        row.addStretch(1)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("Пропорции")
        label.setObjectName("fieldLabel")
        self.ratio_combo = QComboBox()
        for key, title, _ in ASPECT_RATIOS:
            self.ratio_combo.addItem(title, key)
        self.ratio_combo.setCurrentIndex(
            max(0, self.ratio_combo.findData(self._settings.aspect_ratio))
        )
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(self.ratio_combo, 1)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("Если пропорции не сошлись")
        label.setObjectName("fieldLabel")
        self.fit_combo = QComboBox()
        for key, title in FIT_MODES.items():
            self.fit_combo.addItem(title, key)
        self.fit_combo.setCurrentIndex(max(0, self.fit_combo.findData(self._settings.fit_mode)))
        layout.addWidget(label)
        row.addWidget(self.fit_combo, 1)
        layout.addLayout(row)

        layout.addWidget(self._build_anchor_grid())

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("Цвет полей")
        label.setObjectName("fieldLabel")
        self.pad_combo = QComboBox()
        for key, title in PAD_MODES.items():
            self.pad_combo.addItem(title, key)
        self.pad_combo.setCurrentIndex(max(0, self.pad_combo.findData(self._settings.pad_mode)))
        self.pad_color_field = QLineEdit(self._settings.pad_color)
        self.pad_color_field.setFixedWidth(88)
        self.pad_color_field.setPlaceholderText("#FFFFFF")
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(self.pad_combo, 1)
        row.addWidget(self.pad_color_field)
        layout.addLayout(row)

        self.upscale_check = QCheckBox("Увеличивать, если фото меньше")
        self.upscale_check.setChecked(self._settings.allow_upscale)
        self.upscale_check.setToolTip(
            "Выключено — программа отдаст заданный кадр, но фотография в нём "
            "будет меньше, а вокруг появятся поля."
        )
        layout.addWidget(self.upscale_check)

        layout.addWidget(hint("Заданные цифры запоминаются до следующего запуска."))

        self.width_spin.valueChanged.connect(lambda: self._on_side_change("width"))
        self.height_spin.valueChanged.connect(lambda: self._on_side_change("height"))
        self.link_button.toggled.connect(self._on_change)
        self.ratio_combo.currentIndexChanged.connect(self._on_ratio_change)
        self.fit_combo.currentIndexChanged.connect(self._on_change)
        self.pad_combo.currentIndexChanged.connect(self._on_change)
        self.pad_color_field.textChanged.connect(self._on_change)
        self.upscale_check.toggled.connect(self._on_change)
        return block

    def _build_anchor_grid(self) -> QWidget:
        """Девять кнопок вместо списка: куда прижимать кадр, видно сразу."""
        block = QWidget()
        layout = QHBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel("Прижать к")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        layout.addStretch(1)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)
        self.anchor_group = QButtonGroup(self)
        self.anchor_buttons: dict[str, QPushButton] = {}
        order = [
            ("top_left", 0, 0), ("top", 0, 1), ("top_right", 0, 2),
            ("left", 1, 0), ("center", 1, 1), ("right", 1, 2),
            ("bottom_left", 2, 0), ("bottom", 2, 1), ("bottom_right", 2, 2),
        ]
        for key, line, column in order:
            button = QPushButton()
            button.setObjectName("anchorCell")
            button.setCheckable(True)
            button.setFixedSize(22, 22)
            button.setToolTip(ANCHORS[key])
            button.setChecked(self._settings.crop_anchor == key)
            self.anchor_group.addButton(button)
            self.anchor_buttons[key] = button
            grid.addWidget(button, line, column)
            button.toggled.connect(self._on_change)
        layout.addWidget(grid_host)
        return block

    def _reset_size(self) -> None:
        reset_size_fields(self._settings)
        self.load_from(self._settings)
        self._on_change()

    # ------------------------------------------------------------------
    # Формат
    # ------------------------------------------------------------------
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
        self.format_combo.setCurrentIndex(
            max(0, self.format_combo.findData(self._settings.output_format))
        )
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
        advanced_layout.addWidget(self.srgb_check)
        advanced_layout.addWidget(self.progressive_check)

        row = QHBoxLayout()
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
        row.addWidget(sub_label)
        row.addStretch(1)
        row.addWidget(self.subsampling_combo, 1)
        advanced_layout.addLayout(row)

        row = QHBoxLayout()
        threads_label = QLabel("Потоков обработки")
        threads_label.setObjectName("fieldLabel")
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 32)
        self.threads_spin.setSpecialValueText("Авто")
        self.threads_spin.setValue(self._settings.threads)
        self.threads_spin.setFixedWidth(110)
        row.addWidget(threads_label)
        row.addStretch(1)
        row.addWidget(self.threads_spin)
        advanced_layout.addLayout(row)

        self.advanced.setVisible(False)
        card.add(self.advanced)

        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        self.format_combo.currentIndexChanged.connect(self._on_change)
        self.subsampling_combo.currentIndexChanged.connect(self._on_change)
        for widget in (self.metadata_check, self.srgb_check, self.progressive_check):
            widget.toggled.connect(self._on_change)
        self.threads_spin.valueChanged.connect(self._on_change)
        return card

    # ------------------------------------------------------------------
    # Выгрузка
    # ------------------------------------------------------------------
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
        browse.clicked.connect(self.choose_output)
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

        self.rename_check = QCheckBox("Переименовать по шаблону")
        self.rename_check.setChecked(self._settings.rename_enabled)
        card.add(self.rename_check)

        self.rename_block = QWidget()
        rename_layout = QVBoxLayout(self.rename_block)
        rename_layout.setContentsMargins(22, 0, 0, 0)
        rename_layout.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.rename_field = QLineEdit(self._settings.rename_pattern)
        self.rename_field.setPlaceholderText("{name}")
        self.rename_start_spin = QSpinBox()
        self.rename_start_spin.setRange(0, 100000)
        self.rename_start_spin.setPrefix("с ")
        self.rename_start_spin.setValue(self._settings.rename_start)
        self.rename_start_spin.setFixedWidth(84)
        self.rename_start_spin.setToolTip("С какого числа начинать нумерацию")
        row.addWidget(self.rename_field, 1)
        row.addWidget(self.rename_start_spin)
        rename_layout.addLayout(row)
        rename_layout.addWidget(hint(RENAME_HELP))
        card.add(self.rename_block)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("Суффикс к имени")
        label.setObjectName("fieldLabel")
        self.suffix_field = QLineEdit(self._settings.name_suffix)
        self.suffix_field.setPlaceholderText("необязательно, например _web")
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
        self.rename_check.toggled.connect(self._on_change)
        self.rename_field.textChanged.connect(self._on_change)
        self.rename_start_spin.valueChanged.connect(self._on_change)
        return card

    def _build_credits(self) -> QWidget:
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setSpacing(2)
        for text, name in (
            (f"{APP_NAME} {VERSION_LABEL}", "creditsTitle"),
            (f"Разработка – {AUTHOR} · {AUTHOR_HANDLE}", "creditsAuthor"),
        ):
            label = QLabel(text)
            label.setObjectName(name)
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)
        return block

    # ------------------------------------------------------------------
    # Поведение
    # ------------------------------------------------------------------
    def choose_output(self) -> None:
        start = self._settings.output_dir or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Куда складывать результат", start)
        if chosen:
            self.output_field.setText(chosen)
            self._on_change()

    def _toggle_advanced(self) -> None:
        visible = not self.advanced.isVisible()
        self.advanced.setVisible(visible)
        self.advanced_toggle.setText(("▾  " if visible else "▸  ") + "Дополнительно")

    def _on_quality_change(self, _value: int) -> None:
        if self.min_quality_row.value() > self.quality_row.value():
            self.min_quality_row.setValue(self.quality_row.value())
        self._on_change()

    def _on_side_change(self, changed: str) -> None:
        """Связка сторон: правишь одну — вторая идёт следом."""
        if self._building or not self.link_button.isChecked():
            self._on_change()
            return
        ratio = ASPECT_BY_KEY.get(self.ratio_combo.currentData())
        if ratio is None:
            self._on_change()
            return
        wide, high = ratio
        self._building = True
        if changed == "width":
            self.height_spin.setValue(max(1, round(self.width_spin.value() * high / wide)))
        else:
            self.width_spin.setValue(max(1, round(self.height_spin.value() * wide / high)))
        self._building = False
        self._on_change()

    def _on_ratio_change(self, _index: int) -> None:
        """Выбранные пропорции сразу применяются к высоте, ширина — опорная."""
        ratio = ASPECT_BY_KEY.get(self.ratio_combo.currentData())
        if ratio is not None:
            wide, high = ratio
            self._building = True
            self.link_button.setChecked(True)
            self.height_spin.setValue(max(1, round(self.width_spin.value() * high / wide)))
            self._building = False
        self._on_change()

    def _on_change(self, *_args) -> None:
        if self._building:
            return
        self._sync_enabled()
        self.changed.emit()

    def _size_mode(self) -> str:
        for key, button in self.size_buttons.items():
            if button.isChecked():
                return key
        return SIZE_OFF

    @staticmethod
    def _size_mode_of(settings: Settings) -> str:
        if settings.exact_size_enabled:
            return SIZE_EXACT
        return SIZE_LIMIT if settings.max_side_enabled else SIZE_OFF

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
        self.copy_small_check.setEnabled(limited)

        # В режиме без потерь геометрию не трогаем — менять её нечем.
        lossless = mode == MODE_LOSSLESS
        self.size_card.setEnabled(not lossless)
        size_mode = self._size_mode()
        self.limit_block.setVisible(size_mode == SIZE_LIMIT)
        self.exact_block.setVisible(size_mode == SIZE_EXACT)
        self.sharpen_combo.setEnabled(not lossless)

        self.downscale_check.setEnabled(limited)
        downscaling = self.downscale_check.isEnabled() and self.downscale_check.isChecked()
        self.min_side_check.setEnabled(downscaling)
        self.min_side_spin.setEnabled(downscaling and self.min_side_check.isChecked())

        self.pad_color_field.setVisible(self.pad_combo.currentData() == PAD_CUSTOM)
        self.rename_block.setVisible(self.rename_check.isChecked())

    def current_mode(self) -> str:
        for key, button in self.mode_buttons.items():
            if button.isChecked():
                return key
        return MODE_SMART

    def current_anchor(self) -> str:
        for key, button in self.anchor_buttons.items():
            if button.isChecked():
                return key
        return "center"

    # ------------------------------------------------------------------
    def collect(self) -> Settings:
        """Снимает текущее состояние всех виджетов в объект настроек."""
        settings = self._settings
        settings.limit_enabled = self.limit_check.isChecked()
        settings.target_mb = self.limit_spin.value()
        settings.mode = self.current_mode()
        settings.quality = self.quality_row.value()
        settings.min_quality = self.min_quality_row.value()
        settings.sharpen = self.sharpen_combo.currentData()

        size_mode = self._size_mode()
        settings.exact_size_enabled = size_mode == SIZE_EXACT
        settings.max_side_enabled = size_mode == SIZE_LIMIT
        settings.exact_width = self.width_spin.value()
        settings.exact_height = self.height_spin.value()
        settings.link_sides = self.link_button.isChecked()
        settings.aspect_ratio = self.ratio_combo.currentData()
        settings.fit_mode = self.fit_combo.currentData()
        settings.crop_anchor = self.current_anchor()
        settings.pad_mode = self.pad_combo.currentData()
        settings.pad_color = self.pad_color_field.text().strip() or "#FFFFFF"
        settings.allow_upscale = self.upscale_check.isChecked()
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
        settings.rename_enabled = self.rename_check.isChecked()
        settings.rename_pattern = self.rename_field.text()
        settings.rename_start = self.rename_start_spin.value()
        return settings.normalized()

    def load_from(self, settings: Settings) -> None:
        """Расставляет виджеты по готовому набору настроек."""
        self._building = True
        self._settings = settings

        self.limit_check.setChecked(settings.limit_enabled)
        self.limit_spin.setValue(settings.target_mb)
        self.mode_buttons[settings.mode].setChecked(True)
        self.quality_row.setValue(settings.quality)
        self.min_quality_row.setValue(settings.min_quality)
        self.sharpen_combo.setCurrentIndex(max(0, self.sharpen_combo.findData(settings.sharpen)))

        self.size_buttons[self._size_mode_of(settings)].setChecked(True)
        self.width_spin.setValue(settings.exact_width)
        self.height_spin.setValue(settings.exact_height)
        self.link_button.setChecked(settings.link_sides)
        self.ratio_combo.setCurrentIndex(max(0, self.ratio_combo.findData(settings.aspect_ratio)))
        self.fit_combo.setCurrentIndex(max(0, self.fit_combo.findData(settings.fit_mode)))
        self.anchor_buttons.get(settings.crop_anchor, self.anchor_buttons["center"]).setChecked(True)
        self.pad_combo.setCurrentIndex(max(0, self.pad_combo.findData(settings.pad_mode)))
        self.pad_color_field.setText(settings.pad_color)
        self.upscale_check.setChecked(settings.allow_upscale)
        self.max_side_spin.setValue(settings.max_side)
        self.min_side_check.setChecked(settings.min_side_enabled)
        self.min_side_spin.setValue(settings.min_side)
        self.downscale_check.setChecked(settings.allow_downscale)

        self.format_combo.setCurrentIndex(max(0, self.format_combo.findData(settings.output_format)))
        self.metadata_check.setChecked(settings.keep_metadata)
        self.srgb_check.setChecked(settings.convert_to_srgb)
        self.progressive_check.setChecked(settings.progressive)
        self.subsampling_combo.setCurrentIndex(
            max(0, self.subsampling_combo.findData(settings.subsampling))
        )
        self.threads_spin.setValue(settings.threads)

        self.output_field.setText(settings.output_dir)
        self.keep_structure_radio.setChecked(settings.keep_structure)
        self.flat_radio.setChecked(not settings.keep_structure)
        self.conflict_combo.setCurrentIndex(max(0, self.conflict_combo.findData(settings.on_conflict)))
        self.suffix_field.setText(settings.name_suffix)
        self.copy_small_check.setChecked(settings.copy_when_already_small)
        self.rename_check.setChecked(settings.rename_enabled)
        self.rename_field.setText(settings.rename_pattern)
        self.rename_start_spin.setValue(settings.rename_start)

        self._building = False
        self._sync_enabled()

    def set_busy(self, busy: bool) -> None:
        self.setEnabled(not busy)
