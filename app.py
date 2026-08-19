"""Точка входа приложения.

Кроме обычного запуска умеет `--selftest ФАЙЛ`: собранный exe проверяет сам
себя (пресет на месте, геометрия считается, Qt поднимается) и пишет отчёт.
Это единственный способ убедиться, что упаковка не потеряла зависимость, —
из CI собранное окно руками не потрогать.
"""

from __future__ import annotations

import sys
from pathlib import Path


def selftest(report_path: str | None) -> int:
    lines: list[str] = []
    ok = True

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and condition
        lines.append(f"[{'OK ' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

    try:
        import numpy as np
        from PIL import Image

        from lamoda_item_fitter.config import Preset, resource_dir
        from lamoda_item_fitter.fitter import FITTED, fit_image

        preset_file = resource_dir() / "presets" / "lamoda.json"
        check("пресет упакован", preset_file.is_file(), str(preset_file))
        icon_file = resource_dir() / "assets" / "icon.png"
        check("иконка упакована", icon_file.is_file(), str(icon_file))

        preset = Preset.load()
        check("холст из пресета",
              (preset.canvas.width, preset.canvas.height) == (1524, 2200),
              f"{preset.canvas.width}x{preset.canvas.height}")

        array = np.full((900, 1400, 3), 246, np.uint8)
        array[500:700, 200:1100] = 60
        result = fit_image(Image.fromarray(array), preset)
        check("подгонка выполняется", result.status == FITTED, result.reason)
        check("размер результата",
              result.image is not None and result.image.size == (1524, 2200))
        check("низ на линии отступа",
              result.metrics.margins.get("bottom") == preset.margins.bottom,
              str(result.metrics.margins))

        from lamoda_item_fitter.imageio import save_image

        target = Path(report_path or ".").resolve().parent / "_selftest.jpg"
        size, quality = save_image(result.image, target, preset.output)
        check("сохранение JPEG", target.exists() and size > 0,
              f"{size / 1048576:.2f} МБ, качество {quality}")
        target.unlink(missing_ok=True)
    except Exception as error:  # noqa: BLE001 — отчёт важнее трассировки
        ok = False
        lines.append(f"[FAIL] ядро: {type(error).__name__}: {error}")

    try:
        # без дисплея Qt не бросает исключение, а аварийно завершает процесс,
        # поэтому платформу задаём явно — плагины упакованы все разом
        import os

        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication

        from lamoda_item_fitter.config import Preset
        from lamoda_item_fitter.gui.app import MainWindow

        application = QApplication.instance() or QApplication([])
        window = MainWindow(Preset.load())
        check("окно собирается", window.tree.columnCount() == 3)
        window.close()
        application.quit()
    except Exception as error:  # noqa: BLE001
        ok = False
        lines.append(f"[FAIL] интерфейс: {type(error).__name__}: {error}")

    lines.append("ИТОГ: " + ("всё в порядке" if ok else "есть ошибки"))
    text = "\n".join(lines)
    if report_path:
        Path(report_path).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        index = sys.argv.index("--selftest")
        report = sys.argv[index + 1] if len(sys.argv) > index + 1 else None
        return selftest(report)

    from lamoda_item_fitter.gui.app import main as run_gui

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
