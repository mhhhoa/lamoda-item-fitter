# -*- mode: python ; coding: utf-8 -*-
"""Сборка одного самодостаточного exe для Windows.

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
    datas=[(str(ROOT / "presets" / "lamoda.json"), "presets")],
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
    splash.binaries,
    analysis.binaries,
    analysis.datas,
    [],
    name="LamodaItemFitter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico"),
)
