"""Оформление приложения: палитра и таблица стилей Qt."""

from __future__ import annotations

#: Тёмная нейтральная база — на ней глаз честнее оценивает цвета фотографий.
COLORS = {
    "bg": "#0F1114",
    "surface": "#161A20",
    "surface_alt": "#1C212A",
    "surface_hover": "#222833",
    "border": "#272D38",
    "border_strong": "#333B49",
    "text": "#E7EAEF",
    "text_muted": "#8C94A3",
    "text_faint": "#5F6775",
    "accent": "#6E8BFF",
    "accent_hover": "#8098FF",
    "accent_press": "#5C79EE",
    "success": "#41C08A",
    "warning": "#E8B341",
    "danger": "#EF6B67",
}

FONT_STACK = '"Segoe UI Variable Display", "Segoe UI", "Inter", "SF Pro Text", system-ui, sans-serif'


def assets_dir() -> str:
    """Папка с картинками интерфейса — и в исходниках, и в собранном exe."""
    import sys
    from pathlib import Path

    roots = [Path(getattr(sys, "_MEIPASS", "")), Path(__file__).resolve().parents[2]]
    for root in roots:
        candidate = root / "assets"
        if str(root) and candidate.is_dir():
            return candidate.as_posix()
    return ""


def stylesheet() -> str:
    c = COLORS
    assets = assets_dir()
    check = f"image: url({assets}/check.png);" if assets else ""
    check_off = f"image: url({assets}/check_disabled.png);" if assets else ""
    up = f"image: url({assets}/chevron_up.png);" if assets else ""
    down = f"image: url({assets}/chevron_down.png);" if assets else ""
    return f"""
* {{
    font-family: {FONT_STACK};
    font-size: 13px;
    color: {c['text']};
}}

QWidget#root {{ background: {c['bg']}; }}

/* ---------- Шапка ---------- */
QWidget#header {{
    background: {c['surface']};
    border-bottom: 1px solid {c['border']};
}}
QLabel#appTitle {{ font-size: 16px; font-weight: 600; letter-spacing: 0.2px; }}
QLabel#appSubtitle {{ font-size: 12px; color: {c['text_muted']}; }}
QLabel#logoMark {{
    background: {c['accent']};
    color: #0F1114;
    font-size: 15px;
    font-weight: 700;
    border-radius: 9px;
    min-width: 32px; max-width: 32px;
    min-height: 32px; max-height: 32px;
}}

/* ---------- Карточки ---------- */
QFrame#card {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 12px;
}}
QLabel#sectionTitle {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.9px;
    color: {c['text_faint']};
}}
QLabel#hint {{ font-size: 11px; color: {c['text_muted']}; }}
QLabel#creditsTitle {{ font-size: 11px; font-weight: 600; color: {c['text_faint']}; }}
QLabel#creditsAuthor {{ font-size: 11px; color: {c['text_faint']}; }}
QLabel#fieldLabel {{ color: {c['text_muted']}; }}
QFrame#separator {{ background: {c['border']}; max-height: 1px; border: none; }}

/* ---------- Зона перетаскивания ---------- */
QFrame#dropZone {{
    background: {c['surface']};
    border: 1px dashed {c['border_strong']};
    border-radius: 12px;
}}
QFrame#dropZone[hover="true"] {{
    background: {c['surface_alt']};
    border: 1px dashed {c['accent']};
}}
QLabel#dropTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#dropHint {{ font-size: 12px; color: {c['text_muted']}; }}

/* ---------- Кнопки ---------- */
QPushButton {{
    background: {c['surface_alt']};
    border: 1px solid {c['border_strong']};
    border-radius: 8px;
    padding: 7px 14px;
    color: {c['text']};
}}
QPushButton:hover {{ background: {c['surface_hover']}; border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['bg']}; }}
QPushButton:disabled {{ color: {c['text_faint']}; border-color: {c['border']}; background: {c['surface']}; }}

QPushButton#primary {{
    background: {c['accent']};
    border: 1px solid {c['accent']};
    color: #0D1016;
    font-weight: 600;
    padding: 9px 26px;
    border-radius: 9px;
}}
QPushButton#primary:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
QPushButton#primary:pressed {{ background: {c['accent_press']}; }}
QPushButton#primary:disabled {{ background: {c['surface_alt']}; color: {c['text_faint']}; border-color: {c['border']}; }}

QPushButton#danger {{ border-color: {c['border_strong']}; color: {c['danger']}; }}
QPushButton#danger:hover {{ border-color: {c['danger']}; background: {c['surface_hover']}; }}

QPushButton#link {{
    background: transparent; border: none; padding: 3px 2px;
    color: {c['text_muted']}; text-align: left;
}}
QPushButton#link:hover {{ color: {c['accent']}; }}

/* ---------- Поля ввода ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {c['bg']};
    border: 1px solid {c['border_strong']};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {c['accent']};
    selection-color: #0D1016;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {c['text_faint']}; }}
QLineEdit#pathField {{ color: {c['text_muted']}; }}

QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; height: 14px; border: none; background: transparent; margin-right: 2px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; height: 14px; border: none; background: transparent; margin-right: 2px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background: {c['surface_hover']}; border-radius: 4px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ {up} width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ {down} width: 10px; height: 10px; }}

QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ {down} width: 11px; height: 11px; margin-right: 8px; }}
QComboBox QAbstractItemView {{
    background: {c['surface_alt']};
    border: 1px solid {c['border_strong']};
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: {c['accent']};
    selection-color: #0D1016;
}}

/* ---------- Переключатели ---------- */
QCheckBox, QRadioButton {{ spacing: 8px; padding: 2px 0; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QCheckBox::indicator {{ border: 1px solid {c['border_strong']}; border-radius: 5px; background: {c['bg']}; }}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{
    background: {c['accent']}; border-color: {c['accent']}; {check}
}}
QCheckBox::indicator:checked:disabled {{
    background: {c['border_strong']}; border-color: {c['border_strong']}; {check_off}
}}
QRadioButton::indicator {{ border: 1px solid {c['border_strong']}; border-radius: 8px; background: {c['bg']}; }}
QRadioButton::indicator:hover {{ border-color: {c['accent']}; }}
QRadioButton::indicator:checked {{
    border: 1px solid {c['accent']};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {c['accent']}, stop:0.52 {c['accent']}, stop:0.56 {c['bg']}, stop:1 {c['bg']});
}}

/* ---------- Ползунки ---------- */
QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {c['text']}; width: 14px; height: 14px;
    margin: -6px 0; border-radius: 7px; border: none;
}}
QSlider::handle:horizontal:hover {{ background: #FFFFFF; }}
QSlider::groove:horizontal:disabled {{ background: {c['border']}; }}
QSlider::sub-page:horizontal:disabled {{ background: {c['border_strong']}; }}
QSlider::handle:horizontal:disabled {{ background: {c['text_faint']}; }}

/* ---------- Таблица ---------- */
QTableView {{
    background: {c['surface']};
    alternate-background-color: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 12px;
    gridline-color: transparent;
    outline: none;
    selection-background-color: {c['surface_hover']};
    selection-color: {c['text']};
}}
QTableView::item {{ padding: 6px 10px; border: none; border-bottom: 1px solid {c['border']}; }}
QTableView::item:selected {{ background: {c['surface_hover']}; }}
QHeaderView::section {{
    background: {c['surface']};
    color: {c['text_faint']};
    border: none;
    border-bottom: 1px solid {c['border']};
    padding: 9px 8px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
}}
QTableCornerButton::section {{ background: {c['surface']}; border: none; }}

/* ---------- Прокрутка ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border_strong']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['text_faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border_strong']}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---------- Прогресс ---------- */
QProgressBar {{
    background: {c['border']}; border: none; border-radius: 3px;
    height: 6px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}

/* ---------- Подвал ---------- */
QWidget#footer {{ background: {c['surface']}; border-top: 1px solid {c['border']}; }}
QLabel#summary {{ color: {c['text_muted']}; font-size: 12px; }}
QLabel#summaryStrong {{ color: {c['text']}; font-size: 13px; font-weight: 600; }}

QToolTip {{
    background: {c['surface_alt']};
    color: {c['text']};
    border: 1px solid {c['border_strong']};
    border-radius: 6px;
    padding: 6px 9px;
}}
"""
