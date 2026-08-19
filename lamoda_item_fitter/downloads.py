"""Папка «Загрузки» и открытие папки в проводнике."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _windows_downloads() -> Path | None:
    """Спрашивает у Windows реальный путь «Загрузок» (переживает перенос папки)."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    folderid_downloads = GUID(
        0x374DE290, 0x123F, 0x4565,
        (0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B),
    )
    shell = ctypes.windll.shell32
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    buffer = ctypes.c_wchar_p()
    if shell.SHGetKnownFolderPath(ctypes.byref(folderid_downloads), 0, None,
                                  ctypes.byref(buffer)) != 0:
        return None
    try:
        return Path(buffer.value) if buffer.value else None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(buffer)


def _xdg_downloads() -> Path | None:
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "user-dirs.dirs"
    if not config.is_file():
        return None
    for line in config.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith("XDG_DOWNLOAD_DIR"):
            continue
        value = line.split("=", 1)[1].strip().strip('"')
        return Path(os.path.expandvars(value.replace("$HOME", str(Path.home()))))
    return None


def downloads_dir() -> Path:
    """Папка «Загрузки» текущего пользователя; при неудаче — ~/Downloads."""
    resolved: Path | None = None
    try:
        if sys.platform == "win32":
            resolved = _windows_downloads()
        elif sys.platform.startswith("linux"):
            resolved = _xdg_downloads()
    except Exception:
        resolved = None
    if resolved is None or not resolved.is_dir():
        resolved = Path.home() / "Downloads"
    return resolved


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
