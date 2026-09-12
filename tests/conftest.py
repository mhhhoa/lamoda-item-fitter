"""Общая синтетика для тестов.

Сцена строится так, чтобы в ней было всё, что ломает наивные решения:
цветной градиентный фон, подкрашенный фоном товар и отражение под ним.
"""

import numpy as np
import pytest
from scipy import ndimage

from item_fitter import colorspace as cs


def make_scene(
    bg=(0.93, 0.86, 0.79),
    product=(0.62, 0.33, 0.05),
    spill: float = 0.14,
    h: int = 400,
    w: int = 300,
    reflection: float = 0.42,
):
    """Возвращает (кадр sRGB [0,1], истинная альфа товара)."""
    v, u = np.meshgrid(
        np.linspace(-1, 1, h, dtype=np.float32),
        np.linspace(-1, 1, w, dtype=np.float32),
        indexing="ij",
    )
    shading = (1.0 - 0.20 * u**2 - 0.16 * v**2 + 0.05 * v).astype(np.float32)
    lin = np.asarray(bg, np.float32)[None, None, :] * shading[..., None]

    yy, xx = np.mgrid[0:h, 0:w]
    fy, fx = h / 600.0, w / 450.0
    boot = ((xx > 150 * fx) & (xx < 300 * fx) & (yy > 200 * fy) & (yy < 430 * fy)) | (
        (xx > 130 * fx) & (xx < 330 * fx) & (yy >= 430 * fy) & (yy < 470 * fy)
    )
    alpha = ndimage.gaussian_filter(boot.astype(np.float32), 1.2 * fy)

    # Цветной рефлекс фона на товаре — то, что пайплайн должен ослабить.
    #
    # Модель физическая, а не альфа-смешивание. Отражённый от циклорамы свет —
    # это второй источник, подкрашенный в цвет фона, и объект ОСВЕЩАЕТСЯ суммой
    # источников. То есть наблюдаемый цвет = цвет товара, ДОМНОЖЕННЫЙ на смесь
    # нейтрального и цветного света, а не подмешанный к цвету фона.
    #
    # Разница принципиальна: обратной операцией к домножению служит коррекция
    # баланса белого, а к подмешиванию — вычитание. Смоделируй мы рефлекс
    # альфа-смешиванием, инструмент калибровался бы против неверной физики.
    bg_arr = np.asarray(bg, np.float32)
    illuminant = (1 - spill) + spill * (bg_arr / max(float(bg_arr.mean()), 1e-6))
    lit = np.asarray(product, np.float32) * illuminant
    lin = lin * (1 - alpha[..., None]) + lit * alpha[..., None]

    refl = np.zeros((h, w), np.float32)
    rr = (xx > 140 * fx) & (xx < 320 * fx) & (yy >= 470 * fy) & (yy < 540 * fy)
    refl[rr] = np.clip((540 * fy - yy[rr]) / (70 * fy), 0, 1) * reflection
    lin *= (1 - ndimage.gaussian_filter(refl, 6 * fy))[..., None]

    return cs.linear_to_srgb(np.clip(lin, 0, 1)), alpha


@pytest.fixture
def scene():
    return make_scene


@pytest.fixture
def fast_settings():
    """Настройки без нейросети: тесты обязаны идти офлайн и быстро."""
    from item_fitter.config import Settings

    return Settings(matting="simple")
