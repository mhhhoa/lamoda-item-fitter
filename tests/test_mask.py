"""Выделение товара: тень, светлые детали, обрезка краем, мусор."""

import numpy as np

from lamoda_item_fitter.background import estimate_background
from lamoda_item_fitter.mask import build_masks
from tests.conftest import canvas


def masks_for(array, preset):
    background = estimate_background(array, preset.background.border_fraction)
    return build_masks(array, background, preset.mask, preset.background.border_fraction)


def test_dust_and_stamps_are_ignored(preset):
    array = canvas(400, 300)
    array[200:340, 60:240] = 40
    array[10:16, 10:16] = 30          # пылинка
    array[380:392, 250:290] = 90      # подпись в углу

    result = masks_for(array, preset)

    assert result.bbox == (60, 200, 239, 339)
    assert result.components == 1


def test_soft_shadow_stays_out_of_the_box(preset):
    """Тень под товаром опознаётся по затуханию и не смещает низ."""
    array = canvas(400, 300)
    array[200:340, 60:240] = 40
    for step, row in enumerate(range(340, 366)):
        array[row, 70:230] = 249 - int(18 * (1 - step / 26))

    result = masks_for(array, preset)

    assert result.shadow_confirmed
    assert result.item_bbox("exclude")[3] == 339
    assert result.item_bbox("include")[3] > 339


def test_light_sole_is_part_of_the_item(preset):
    """Ровная светлая подошва — это товар, а не тень: низ должен её учесть."""
    array = canvas(400, 300)
    array[200:340, 60:240] = 40
    array[340:366, 60:240] = 234

    result = masks_for(array, preset)

    assert not result.shadow_confirmed
    assert result.item_bbox("exclude")[3] == 365


def test_side_crop_is_detected(preset):
    array = canvas(400, 300)
    array[200:340, 0:240] = 40

    result = masks_for(array, preset)

    assert result.cropped_sides == ["left"]


def test_bottom_crop_does_not_block_fitting(preset):
    """Плотно скадрированный снизу кадр подгоняется штатно."""
    array = canvas(400, 300)
    array[200:400, 60:240] = 40

    result = masks_for(array, preset)

    assert result.touches["bottom"]
    assert result.cropped_sides == []


def test_threshold_follows_background_noise(preset):
    quiet = masks_for_array_threshold(canvas(400, 300), preset)
    noisy = masks_for_array_threshold(canvas(400, 300, noise=6), preset)

    assert noisy > quiet


def masks_for_array_threshold(array, preset):
    array[200:340, 60:240] = 40
    return masks_for(array, preset).threshold


def test_two_shoes_are_kept_together(preset):
    array = canvas(400, 400)
    array[200:340, 40:180] = 40
    array[220:340, 220:360] = 40

    result = masks_for(array, preset)

    assert result.components == 2
    assert result.bbox == (40, 200, 359, 339)
