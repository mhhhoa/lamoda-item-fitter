"""Системные папки пользователя и открытие папки в проводнике."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


#: известные папки Windows: спрашивать систему надёжнее, чем складывать путь
#: из имени пользователя — папку могли перенести на другой диск
FOLDERID_DOWNLOADS = (0x374DE290, 0x123F, 0x4565,
                      (0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
FOLDERID_DESKTOP = (0xB4BFCC3A, 0xDB2C, 0x424C,
                    (0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41))


def _windows_known_folder(folder_id: tuple) -> Path | None:
    """Спрашивает у Windows реальный путь известной папки."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    first, second, third, rest = folder_id
    guid = GUID(first, second, third, (ctypes.c_ubyte * 8)(*rest))
    shell = ctypes.windll.shell32
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    buffer = ctypes.c_wchar_p()
    if shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                  ctypes.byref(buffer)) != 0:
        return None
    try:
        return Path(buffer.value) if buffer.value else None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(buffer)


def _xdg_dir(key: str) -> Path | None:
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "user-dirs.dirs"
    if not config.is_file():
        return None
    for line in config.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith(key):
            continue
        value = line.split("=", 1)[1].strip().strip('"')
        return Path(os.path.expandvars(value.replace("$HOME", str(Path.home()))))
    return None


def _user_dir(folder_id: tuple, xdg_key: str, fallback: str) -> Path:
    resolved: Path | None = None
    try:
        if sys.platform == "win32":
            resolved = _windows_known_folder(folder_id)
        elif sys.platform.startswith("linux"):
            resolved = _xdg_dir(xdg_key)
    except Exception:
        resolved = None
    if resolved is None or not resolved.is_dir():
        resolved = Path.home() / fallback
    return resolved


def downloads_dir() -> Path:
    """Папка «Загрузки» текущего пользователя; при неудаче — ~/Downloads."""
    return _user_dir(FOLDERID_DOWNLOADS, "XDG_DOWNLOAD_DIR", "Downloads")


def desktop_dir() -> Path:
    """Рабочий стол текущего пользователя; при неудаче — ~/Desktop."""
    return _user_dir(FOLDERID_DESKTOP, "XDG_DESKTOP_DIR", "Desktop")


def open_folder(path: Path | str) -> None:
    """Показывает папку в проводнике / Finder / файловом менеджере."""
    path = str(path)
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass
