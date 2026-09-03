# -*- mode: python ; coding: utf-8 -*-
"""Сборка самодостаточной программы для Windows.

Собирается как папка (onedir), не как один exe (onefile). Обработка идёт
в отдельных процессах, а каждый такой процесс — это повторный запуск того
же исполняемого файла; в режиме onefile это означает, что ПЕРЕД каждым
запуском рабочего процесса заново распаковываются все ~70 МБ во временную
папку — отсюда и нагрузка на диск/антивирус при пачке файлов, и
предупреждения Windows о неудалённой временной папке. В onedir файлы уже
лежат распакованными рядом с exe, и рабочий процесс стартует напрямую.

Из scipy нужен только ndimage — он тянет за собой лишь `_lib` и `special`,
поэтому крупные подпакеты исключены. Из Qt нужны Core, Gui и Widgets.
Если исключение окажется лишним, это поймает `--selftest` в CI.
"""

from pathlib import Path

ROOT = Path(SPECPATH)

SCIPY_UNUSED = [
    "scipy.optimize", "scipy.stats", "scipy.sparse", "scipy.interpolate",
    "scipy.signal", "scipy.spatial", "scipy.fft", "scipy.fftpack",
    "scipy.integrate", "scipy.io", "scipy.cluster", "scipy.odr",
    "scipy.constants", "scipy.datasets", "scipy.differentiate",
]

QT_UNUSED = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
]

analysis = Analysis(
    ["app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "presets" / "lamoda.json"), "presets"),
        (str(ROOT / "assets" / "icon.png"), "assets"),
    ],
    hiddenimports=["scipy.ndimage", "scipy.special"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=SCIPY_UNUSED + QT_UNUSED + [
        "matplotlib", "pandas", "pytest", "IPython", "notebook", "setuptools",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

splash = Splash(
    str(ROOT / "assets" / "splash.png"),
    binaries=analysis.binaries,
    datas=analysis.datas,
    text_pos=None,
    always_on_top=True,
)

exe = EXE(
    pyz,
    analysis.scripts,
    splash,
    [],
    exclude_binaries=True,  # бинарники едут рядом папкой, а не внутрь exe
    name="LamodaItemFitter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico"),
    version=str(ROOT / "assets" / "version_info.txt"),
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    splash.binaries,
    strip=False,
    upx=False,
    name="LamodaItemFitter",
)
