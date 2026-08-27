"""Точка входа приложения."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .core.settings import Settings
from .ui.main_window import MainWindow
from .ui.theme import stylesheet


def _icon_path() -> Path | None:
    # В собранном виде ресурсы лежат рядом с исполняемым файлом.
    roots = [Path(getattr(sys, "_MEIPASS", "")), Path(__file__).resolve().parent.parent]
    for root in roots:
        candidate = root / "assets" / "icon.png"
        if root and candidate.exists():
            return candidate
    return None


def main() -> int:
    if "--selftest" in sys.argv:
        from pathlib import Path as _Path

        from .selftest import run

        arguments = [a for a in sys.argv[1:] if a != "--selftest"]
        return run(_Path(arguments[0]) if arguments else None)

    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setOrganizationName("WeightFitter")
    application.setStyle("Fusion")
    application.setStyleSheet(stylesheet())

    icon = _icon_path()
    if icon is not None:
        application.setWindowIcon(QIcon(str(icon)))

    window = MainWindow(Settings.load())
    window.show()
    _close_splash()
    return application.exec()


def _close_splash() -> None:
    """Убирает заставку собранного exe, как только окно готово."""
    try:
        import pyi_splash  # доступен только внутри собранного приложения

        pyi_splash.close()
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
