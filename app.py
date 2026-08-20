"""Точка входа приложения.

Кроме обычного запуска умеет `--selftest ФАЙЛ`: собранный exe проверяет сам
себя (пресет на месте, геометрия считается, Qt поднимается) и пишет отчёт.
Это единственный способ убедиться, что упаковка не потеряла зависимость, —
из CI собранное окно руками не потрогать.
"""

from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

# Обязательно до всего остального: обработка идёт в отдельных процессах, а в
# собранном exe дочерний процесс — это повторный запуск того же файла.
# Без этой строки он вместо работы открыл бы ещё одно окно.
multiprocessing.freeze_support()


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

        work = Path(report_path or ".").resolve().parent
        target = work / "_selftest.jpg"
        size, quality = save_image(result.image, target, preset.output)
        check("сохранение JPEG", target.exists() and size > 0,
              f"{size / 1048576:.2f} МБ, качество {quality}")
        target.unlink(missing_ok=True)

        # тот самый сценарий, на котором программа закрывалась: сбойный файл
        # посреди пачки обязан лишь получить статус, а очередь — дойти до конца
        import shutil

        from lamoda_item_fitter.batch import (
            COPY, FAILED, apply_policy, inspect_one, plan, process_one, summarize,
        )
        from lamoda_item_fitter.runner import run_isolated

        sandbox = work / "_selftest_batch"
        shutil.rmtree(sandbox, ignore_errors=True)
        (sandbox / "src").mkdir(parents=True)
        for index in (1, 3):
            Image.fromarray(array).save(sandbox / "src" / f"{index}.jpg")
        (sandbox / "src" / "2.jpg").write_text("не картинка", encoding="utf-8")

        jobs, _ = apply_policy(
            plan([sandbox / "src"], preset, output_root=sandbox / "out"), COPY)
        # заодно проверяем, что в собранном виде вообще запускаются рабочие
        # процессы: без этого изоляция от падений не работала бы
        outcomes = run_isolated(jobs, preset, process_one, workers=2)
        counts = summarize(outcomes)
        check("сбойный файл не останавливает пачку",
              len(outcomes) == 3 and counts.get(FITTED) == 2 and counts.get(FAILED) == 1,
              f"обработано {len(outcomes)} из 3, {counts}")
        check("у сбойного файла есть причина",
              all(o.reason for o in outcomes if o.status == FAILED))

        verdicts = run_isolated(jobs, preset, inspect_one, workers=2)
        check("анализ отрабатывает по всем файлам", len(verdicts) == 3,
              f"вердиктов {len(verdicts)}")
        shutil.rmtree(sandbox, ignore_errors=True)
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
        check("окно собирается", window.tree.columnCount() == 4,
              f"колонок {window.tree.columnCount()}")
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
