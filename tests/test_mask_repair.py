"""Тесты починки маски.

Светлые пятна на готовом кадре возникают, когда нейросеть помечает кусок внутри
товара как фон: пайплайн осветляет всё, что считает фоном. Эти тесты фиксируют
и саму починку, и её границу — настоящий просвет фона трогать нельзя.
"""

import numpy as np
import pytest
from scipy import ndimage

from item_fitter import background as bgmod
from item_fitter import colorspace as cs
from item_fitter import config, matting, pipeline


def _fit(srgb, alpha):
    lin = cs.srgb_to_linear(srgb)
    return lin, bgmod.fit_background(lin, alpha)


def test_hole_inside_product_is_filled(scene):
    """Островок «фона», зажатый товаром и не похожий на фон, — это ошибка маски."""
    srgb, alpha_true = scene()
    alpha = alpha_true.copy()

    yy, xx = np.mgrid[: alpha.shape[0], : alpha.shape[1]]
    core = ndimage.binary_erosion(alpha_true > 0.9, iterations=8)
    cy, cx = (int(v) for v in ndimage.center_of_mass(core))
    hole = (yy - cy) ** 2 + (xx - cx) ** 2 < 90
    assert core[hole].all(), "дыру нужно пробивать внутри товара"
    alpha[hole] = 0.0

    lin, model = _fit(srgb, alpha)
    repaired, stats = matting.repair_mask(lin, alpha, model)

    assert stats["filled_px"] >= int(hole.sum() * 0.9)
    assert repaired[hole].min() > 0.9, "дыра не закрылась"


def test_genuine_background_gap_is_left_alone(scene):
    """Просвет настоящего фона внутри силуэта трогать нельзя.

    Он тоже не дотягивается до края кадра, поэтому одной геометрии мало —
    решает совпадение с моделью фона.
    """
    srgb, alpha_true = scene()
    lin_true = cs.srgb_to_linear(srgb)

    core = ndimage.binary_erosion(alpha_true > 0.9, iterations=8)
    cy, cx = (int(v) for v in ndimage.center_of_mass(core))
    yy, xx = np.mgrid[: alpha_true.shape[0], : alpha_true.shape[1]]
    gap = (yy - cy) ** 2 + (xx - cx) ** 2 < 90

    # В просвете видно настоящий фон, а не товар.
    alpha = alpha_true.copy()
    alpha[gap] = 0.0
    lin = lin_true.copy()
    _, model_probe = _fit(srgb, alpha)
    lin[gap] = model_probe.surface[gap]

    model = bgmod.fit_background(lin, alpha)
    repaired, stats = matting.repair_mask(lin, alpha, model)

    assert stats["filled_px"] == 0, "настоящий просвет фона был ошибочно замазан"
    assert repaired[gap].max() < 0.1


def test_speck_of_product_in_background_is_dropped(scene):
    """Ложное пятнышко «товара» посреди фона убирается, иначе останется точкой на белом."""
    srgb, alpha_true = scene()
    alpha = alpha_true.copy()
    alpha[12:18, 12:18] = 1.0  # угол кадра — там заведомо чистый фон

    lin, model = _fit(srgb, alpha)
    repaired, stats = matting.repair_mask(lin, alpha, model)

    assert stats["removed_px"] > 0
    assert repaired[12:18, 12:18].max() < 0.1


def test_real_product_detail_is_not_dropped(scene):
    """Мелкая, но настоящая деталь товара обязана уцелеть.

    Отличие от предыдущего случая только в цвете: деталь не похожа на фон.
    """
    srgb, alpha_true = scene()
    lin = cs.srgb_to_linear(srgb)

    alpha = alpha_true.copy()
    patch = (slice(12, 20), slice(12, 20))
    alpha[patch] = 1.0
    lin[patch] = np.array([0.05, 0.04, 0.04], dtype=np.float32)  # тёмная пряжка

    model = bgmod.fit_background(lin, alpha)
    repaired, stats = matting.repair_mask(lin, alpha, model)

    assert repaired[patch].min() > 0.9, "настоящая деталь товара была стёрта"


def test_pipeline_no_longer_leaves_pale_blotch(scene):
    """Сквозная проверка: дырявая маска больше не даёт бледного пятна на товаре."""
    srgb, alpha_true = scene(bg=(0.82, 0.86, 0.92), product=(0.42, 0.33, 0.27))

    core = ndimage.binary_erosion(alpha_true > 0.9, iterations=8)
    cy, cx = (int(v) for v in ndimage.center_of_mass(core))
    yy, xx = np.mgrid[: alpha_true.shape[0], : alpha_true.shape[1]]
    hole = (yy - cy) ** 2 + (xx - cx) ** 2 < 90

    broken = alpha_true.copy()
    broken[hole] = 0.0
    around = core & ~ndimage.binary_dilation(hole, iterations=6)

    def blotch(repair_on: bool) -> float:
        settings = config.Settings(matting="simple", repair_mask=repair_on)
        res = pipeline.process_array(srgb, settings, alpha=broken)
        return float(res.image[hole].mean() - res.image[around].mean())

    without = blotch(False)
    with_repair = blotch(True)

    assert without > 0.02, "тест бессмысленен: пятно не воспроизвелось"
    assert abs(with_repair) < 0.005, (
        f"пятно осталось: было +{without:.3f}, стало {with_repair:+.3f}"
    )


def test_repair_is_reported_to_qa(scene):
    """Дырявая маска обязана попасть в отчёт: иначе о ней никто не узнает."""
    srgb, alpha_true = scene()
    core = ndimage.binary_erosion(alpha_true > 0.9, iterations=6)
    broken = alpha_true.copy()
    broken[core] = 0.0  # огромная дыра во весь товар

    res = pipeline.process_array(srgb, config.Settings(matting="simple"), alpha=broken)
    assert res.report.metrics["mask_filled_px"] > 0
    assert res.verdict != "OK"
    assert any("дыряв" in n for n in res.report.notes)


def test_white_corners_are_no_longer_a_failure(scene):
    """Недо-белый угол — замечание, а не ошибка: на приёмку пара единиц не влияет."""
    srgb, _ = scene()
    settings = config.Settings(matting="simple", min_white=255)  # заведомо придирчиво
    res = pipeline.process_array(srgb, settings)
    assert res.verdict != "FAIL"
