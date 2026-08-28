# -*- mode: python ; coding: utf-8 -*-
"""Сборка одного самодостаточного .exe: pyinstaller --noconfirm build.spec"""

from PyInstaller.utils.hooks import collect_all

heif_datas, heif_binaries, heif_hidden = collect_all("pillow_heif")
mozjpeg_datas, mozjpeg_binaries, mozjpeg_hidden = collect_all("mozjpeg_lossless_optimization")

# _mozjpeg_opti — модуль на cffi, и _cffi_backend он тянет на уровне C, куда
# анализатор PyInstaller не заглядывает. Без этой строки библиотека не
# импортируется в собранном виде, а режим «без потерь» молча деградирует.
CFFI_IMPORTS = ["_cffi_backend", "cffi"]

# Модули, которые тянутся за PySide6, но приложению не нужны.
EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtWebSockets",
    "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "numpy", "scipy", "matplotlib", "pytest", "IPython",
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=heif_binaries + mozjpeg_binaries,
    datas=[("assets", "assets")] + heif_datas + mozjpeg_datas,
    hiddenimports=CFFI_IMPORTS + heif_hidden + mozjpeg_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

# Заставка нужна из-за одного файла: распаковка PySide6 занимает пару секунд,
# и без неё двойной клик выглядит так, будто ничего не произошло.
splash = Splash(
    "assets/splash.png",
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.datas,
    [],
    name="ImgFitter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/icon.ico",
    # Название, версия и автор в свойствах файла Windows.
    version="version_info.txt",
)
