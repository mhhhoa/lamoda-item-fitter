"""Оформление окна: две палитры и один набор правил."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


@dataclass(frozen=True)
class Palette:
    background: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    success: str
    warning: str
    danger: str


LIGHT = Palette(
    background="#ffffff", surface="#ffffff", surface_alt="#f6f6f7", border="#e3e3e6",
    text="#111114", muted="#77777f", accent="#111114", accent_text="#ffffff",
    success="#15803d", warning="#b45309", danger="#b91c1c",
)

DARK = Palette(
    background="#131316", surface="#1a1a1e", surface_alt="#202026", border="#2c2c33",
    text="#f2f2f4", muted="#9a9aa4", accent="#f2f2f4", accent_text="#131316",
    success="#4ade80", warning="#fbbf24", danger="#f87171",
)


def current_palette() -> Palette:
    """Палитра по системной теме; при неизвестной теме — светлая."""
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
    except AttributeError:  # Qt старше 6.5
        return LIGHT
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


def stylesheet(p: Palette) -> str:
    return f"""
    QWidget {{
        background: {p.background};
        color: {p.text};
        font-size: 13px;
    }}
    QLabel#title {{ font-size: 19px; font-weight: 600; }}
    QLabel#subtitle {{ color: {p.muted}; }}
    QLabel#hint {{ color: {p.muted}; }}
    QLabel#fieldHint {{ color: {p.muted}; font-size: 11px; padding: 0 0 4px 0; }}
    QLabel#creditProduct {{ color: {p.text}; font-size: 12px; font-weight: 600; }}
    QLabel#credit {{ color: {p.muted}; font-size: 11px; padding-top: 1px; }}
    QLabel#dropTitle {{ font-size: 16px; font-weight: 600; }}

    QFrame#dropZone {{
        border: 2px dashed {p.border};
        border-radius: 14px;
        background: {p.surface_alt};
    }}
    QFrame#dropZone[hover="true"] {{ border-color: {p.accent}; }}
    QFrame#card {{
        border: 1px solid {p.border};
        border-radius: 12px;
        background: {p.surface};
    }}

    QPushButton {{
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 7px 14px;
        background: {p.surface};
    }}
    QPushButton:hover {{ background: {p.surface_alt}; }}
    QPushButton:disabled {{ color: {p.muted}; }}
    QPushButton#primary {{
        background: {p.accent};
        color: {p.accent_text};
        border: 1px solid {p.accent};
        font-weight: 600;
        padding: 9px 22px;
    }}
    QPushButton#primary:disabled {{ background: {p.border}; color: {p.muted}; border-color: {p.border}; }}
    QPushButton#link {{
        border: none; background: transparent; color: {p.muted};
        padding: 2px 0; text-align: left;
    }}
    QPushButton#link:hover {{ color: {p.text}; }}

    QTreeWidget {{
        border: 1px solid {p.border};
        border-radius: 12px;
        background: {p.surface};
        outline: none;
    }}
    QTreeWidget::item {{ padding: 6px 4px; border-bottom: 1px solid {p.surface_alt}; }}
    QTreeWidget::item:selected {{ background: {p.surface_alt}; color: {p.text}; }}
    QHeaderView::section {{
        background: {p.surface};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: 8px 6px;
        color: {p.muted};
    }}

    QProgressBar {{
        border: none; border-radius: 3px; background: {p.surface_alt};
        height: 6px; text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: 3px; }}

    QComboBox, QSpinBox, QLineEdit {{
        border: 1px solid {p.border}; border-radius: 8px; padding: 6px 8px;
        background: {p.surface};
    }}
    QCheckBox {{ spacing: 8px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
    QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """
