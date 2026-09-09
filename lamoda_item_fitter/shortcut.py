"""Ярлык программы на рабочем столе.

Отдельного установщика у программы нет и не нужно: ещё один неподписанный
exe означал бы второе окно SmartScreen у каждого коллеги и лишние десятки
мегабайт в архиве. Вместо этого ярлык умеет делать сама программа — по
ключу `--create-shortcut` или кнопкой в настройках, а лежащий рядом
«Создать ярлык на рабочем столе.bat» просто зовёт её с этим ключом.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path, PurePath

from . import APP_NAME
from .downloads import desktop_dir

LINK_NAME = f"{APP_NAME}.lnk"
#: окно консоли не должно мелькать: программа оконная, и вспышка чёрного
#: прямоугольника читается как сбой
_NO_WINDOW = 0x08000000


class ShortcutError(RuntimeError):
    """Ярлык создать не удалось — с человеческим объяснением почему."""


def program_path() -> Path:
    """Путь к самой программе, на который будет указывать ярлык."""
    if not getattr(sys, "frozen", False):
        raise ShortcutError(
            "ярлык создаётся только для собранной программы, а не для запуска из исходников")
    return Path(sys.executable).resolve()


def shortcut_script(target: PurePath, link: PurePath) -> str:
    """Скрипт PowerShell, создающий ярлык.

    Вынесен отдельной функцией, чтобы его можно было проверить тестом на
    любой системе: сама запись .lnk доступна только под Windows. Одинарные
    кавычки внутри путей удваиваются — иначе имя пользователя с апострофом
    (а такие бывают) оборвало бы строку и превратило остаток пути в команду.
    """
    def quoted(value: PurePath | str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    return "; ".join([
        "$shell = New-Object -ComObject WScript.Shell",
        f"$link = $shell.CreateShortcut({quoted(link)})",
        f"$link.TargetPath = {quoted(target)}",
        f"$link.WorkingDirectory = {quoted(target.parent)}",
        f"$link.Description = {quoted(APP_NAME)}",
        "$link.Save()",
    ])


def create_desktop_shortcut(target: Path | None = None) -> Path:
    """Кладёт ярлык программы на рабочий стол и возвращает путь ярлыка.

    Ярлык указывает на текущее место программы, поэтому папку после этого
    лучше не переносить: перенесёте — ярлык придётся создать заново.
    """
    if sys.platform != "win32":
        raise ShortcutError("ярлыки на рабочем столе умеет создавать только Windows")

    target = target or program_path()
    if not target.is_file():
        raise ShortcutError(f"файл программы не найден: {target}")

    desktop = desktop_dir()
    if not desktop.is_dir():
        raise ShortcutError(f"папка рабочего стола не найдена: {desktop}")

    link = desktop / LINK_NAME
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             shortcut_script(target, link)],
            capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW,
        )
    except FileNotFoundError as error:
        raise ShortcutError("в системе не нашёлся PowerShell") from error
    except subprocess.TimeoutExpired as error:
        raise ShortcutError("создание ярлыка заняло слишком долго") from error

    if completed.returncode != 0 or not link.is_file():
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise ShortcutError(detail[-1] if detail else "Windows не дала создать ярлык")
    return link
