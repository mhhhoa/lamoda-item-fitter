"""Оркестрация обработки одного кадра.

Порядок шагов не произволен:

  1. грубая маска объекта;
  2. фит модели фона B(x, y) — ей нужна только зона, где маска близка к нулю;
  3. починка маски по B — островки «фона» внутри товара возвращаются товару;
  4. повторный фит B по починенной маске;
  5. уточнение кромки по B — она становится пиксельно точной;
  6. нормализация фона делением, сборка объекта поверх, дотяжка белого.

Шаги 3-5 — это разрешение курицы и яйца: точная маска нужна для хорошей модели фона,
а хорошая модель фона нужна для точной маски. Одной итерации достаточно.

Починка (шаг 3) идёт ДО уточнения кромки, а не после: дырка внутри товара искажает
сам фит модели фона, а по искажённой модели уточнять кромку уже бессмысленно.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import background as bgmod
from . import compose as comp
from . import finish as finmod
from . import matting as matmod
from . import qa as qamod
from .colorspace import linear_to_srgb, load_srgb, save_jpeg, srgb_to_linear
from .config import Settings

__all__ = ["ProcessResult", "process_array", "process_file"]


@dataclass
class ProcessResult:
    image: np.ndarray  # итог, sRGB [0,1]
    original: np.ndarray  # исходник, sRGB [0,1]
    alpha: np.ndarray
    model: bgmod.BackgroundModel
    report: qamod.QAReport
    timing: dict = field(default_factory=dict)
    source: Path | None = None
    output: Path | None = None
    bytes_written: int | None = None

    @property
    def verdict(self) -> str:
        return self.report.verdict


def process_array(
    srgb: np.ndarray,
    settings: Settings,
    matte_fn=None,
    alpha: np.ndarray | None = None,
) -> ProcessResult:
    """Обрабатывает кадр в памяти.

    matte_fn — готовая функция матирования, чтобы не пересоздавать сессию нейросети
        на каждом кадре пакета.
    alpha — уже посчитанная маска. Нужна для подбора параметров: матирование не
        зависит от художественных настроек, поэтому при переборе по сетке его
        достаточно выполнить один раз на кадр, а не на каждую комбинацию.
    """
    t = {}
    original = np.clip(np.asarray(srgb, dtype=np.float32), 0.0, 1.0)

    t0 = time.perf_counter()
    if alpha is None:
        if matte_fn is None:
            matte_fn = matmod.get_backend(settings.matting, settings.matting_post_process)
        alpha = matte_fn(original)
    alpha = np.clip(np.asarray(alpha, dtype=np.float32), 0.0, 1.0)
    t["matting"] = time.perf_counter() - t0

    lin = srgb_to_linear(original)

    t0 = time.perf_counter()
    model = bgmod.fit_background(lin, alpha, degree=settings.poly_degree)
    repair_stats: dict = {"filled_px": 0, "removed_px": 0}

    if settings.repair_mask and not model.degenerate:
        alpha, repair_stats = matmod.repair_mask(lin, alpha, model)
        if repair_stats["filled_px"] or repair_stats["removed_px"]:
            model = bgmod.fit_background(lin, alpha, degree=settings.poly_degree)

    if settings.refine_alpha and not model.degenerate:
        alpha = matmod.refine_alpha_from_background(lin, alpha, model)
        if settings.repair_mask:
            # Уточнение кромки способно само пробить мелкие дыры там, где товар
            # по цвету близок к фону. Второй проход дешёвый и их закрывает.
            alpha, again = matmod.repair_mask(lin, alpha, model)
            repair_stats = {k: repair_stats[k] + again[k] for k in repair_stats}
        model = bgmod.fit_background(lin, alpha, degree=settings.poly_degree)
    t["background"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    ratio = comp.background_ratio_field(lin, model, alpha)
    if settings.reflection_strength != 1.0:
        ratio = np.clip(1.0 - (1.0 - ratio) * settings.reflection_strength, 0.0, 1.0)

    wb = bgmod.white_balance_factor(model, settings.wb_strength) if settings.wb_strength else None
    out = linear_to_srgb(comp.compose(lin, alpha, model, ratio, wb))
    out = bgmod.white_roll_off(
        out,
        knee_low=settings.knee_low,
        knee_high=settings.knee_high,
        protect=comp.protect_mask(alpha),
    )
    out = finmod.apply_target_background(out, alpha, settings.target_bg)
    t["compose"] = time.perf_counter() - t0

    # QA считается ДО смены геометрии, чтобы before и after были попиксельно сравнимы.
    report = qamod.evaluate(original, out, alpha, model, settings, repair=repair_stats)

    if settings.geometry_mode != "keep":
        out = finmod.fit_geometry(
            out,
            settings.geometry_mode,
            settings.out_width,
            settings.out_height,
            settings.target_bg,
        )

    t["total"] = sum(t.values())
    return ProcessResult(
        image=out, original=original, alpha=alpha, model=model, report=report, timing=t
    )


def process_file(
    src: str | Path,
    dst: str | Path,
    settings: Settings,
    matte_fn=None,
) -> ProcessResult:
    """Читает файл, обрабатывает, пишет JPEG. Возвращает результат с метриками."""
    src, dst = Path(src), Path(dst)
    srgb, _meta = load_srgb(src)
    result = process_array(srgb, settings, matte_fn=matte_fn)
    result.source = src
    result.output = dst
    result.bytes_written = save_jpeg(
        dst, result.image, quality=settings.jpeg_quality, max_bytes=settings.max_bytes
    )
    result.report.metrics["file_kb"] = round(result.bytes_written / 1024)
    # Белизну фона подтверждаем по записанному файлу, а не по массиву в памяти.
    qamod.verify_written_file(dst, settings, result.report)
    return result
