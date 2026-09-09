"""Создание ярлыка глазами пользователя: нажал — и сразу видно, чем кончилось.

Тем же кодом пользуются оба входа: кнопка в настройках и запуск программы с
ключом `--create-shortcut` (так её зовёт «Создать ярлык на рабочем столе.bat»).
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from .. import APP_NAME
from ..shortcut import ShortcutError, create_desktop_shortcut


def make_shortcut(parent: QWidget | None = None) -> bool:
    """Создаёт ярлык и показывает результат обычным окном. True — получилось."""
    try:
        link = create_desktop_shortcut()
    except ShortcutError as error:
        QMessageBox.warning(
            parent, APP_NAME,
            f"Не удалось создать ярлык.\n\n{error}\n\n"
            "Ярлык можно сделать вручную: правый клик по файлу программы → "
            "«Отправить» → «Рабочий стол (создать ярлык)».",
        )
        return False
    QMessageBox.information(
        parent, APP_NAME,
        f"Готово — ярлык «{link.stem}» лежит на рабочем столе.\n\n"
        "Запускать программу теперь можно с него. Если папку с программой "
        "переместить, ярлык перестанет работать — создайте его заново.",
    )
    return True


def run_installer() -> int:
    """Точка входа для `--create-shortcut`: окно с результатом и выход.

    Своё приложение Qt поднимается прямо здесь: программа запущена ради
    одного действия, главное окно ей не нужно.
    """
    application = QApplication.instance() or QApplication([])
    application.setApplicationName(APP_NAME)
    return 0 if make_shortcut() else 1
