"""Ярлык на рабочем столе.

Саму запись .lnk делает Windows, и проверить её отсюда нечем. Зато можно
проверить то, что ломается тише всего: как складывается команда PowerShell
и что программа отвечает, когда ярлык создать нельзя.
"""

import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from lamoda_item_fitter.downloads import desktop_dir, downloads_dir
from lamoda_item_fitter.shortcut import (
    LINK_NAME, ShortcutError, create_desktop_shortcut, program_path, shortcut_script,
)


def test_script_points_the_link_at_the_program():
    # windows-путь берём явным типом: на Linux обычный Path не делит его по
    # обратным слэшам, и проверка молча стала бы бессмысленной
    script = shortcut_script(PureWindowsPath(r"C:\Программы\LamodaItemFitter-1.4.exe"),
                             PureWindowsPath(r"C:\Users\Иванова\Desktop\Lamoda Item Fitter.lnk"))

    assert "CreateShortcut('C:\\Users\\Иванова\\Desktop\\Lamoda Item Fitter.lnk')" in script
    assert "$link.TargetPath = 'C:\\Программы\\LamodaItemFitter-1.4.exe'" in script
    # рабочая папка — рядом с программой: иначе относительные пути внутри
    # программы поедут от того места, откуда её позвал ярлык
    assert "$link.WorkingDirectory = 'C:\\Программы'" in script
    assert script.endswith("$link.Save()")


def test_apostrophe_in_the_path_cannot_break_the_command():
    """Имя пользователя с апострофом оборвало бы строку и стало командой."""
    script = shortcut_script(PurePosixPath("/home/O'Brien/app.exe"),
                             PurePosixPath("/home/O'Brien/link.lnk"))

    assert "'/home/O''Brien/app.exe'" in script
    assert "'/home/O''Brien/link.lnk'" in script
    assert "'/home/O''Brien'" in script
    assert "O'Brien'" not in script.replace("O''Brien", "")  # неудвоенных не осталось


def test_link_is_named_after_the_program():
    assert LINK_NAME == "Lamoda Item Fitter.lnk"


def test_running_from_sources_says_so():
    """Из исходников ярлыку не на что указывать — и об этом надо сказать прямо."""
    with pytest.raises(ShortcutError, match="собранной"):
        program_path()


@pytest.mark.skipif(sys.platform == "win32", reason="проверяем поведение вне Windows")
def test_other_systems_get_a_plain_refusal():
    with pytest.raises(ShortcutError, match="Windows"):
        create_desktop_shortcut(Path("/tmp/whatever.exe"))


def test_desktop_and_downloads_are_different_folders():
    """Обе папки спрашиваются у системы одним механизмом — легко перепутать."""
    assert desktop_dir() != downloads_dir()
    assert desktop_dir().name in ("Desktop", "Рабочий стол")
