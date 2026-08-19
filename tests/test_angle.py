"""Классификация ракурса по силуэту."""

import numpy as np

from lamoda_item_fitter.angle import PAIR, SIDE_OR_SOLE, TOP, classify
from lamoda_item_fitter.background import estimate_background
from lamoda_item_fitter.mask import build_masks
from tests.conftest import canvas


def kind_of(array, preset):
    background = estimate_background(array, preset.background.border_fraction)
    result = build_masks(array, background, preset.mask, preset.background.border_fraction)
    return classify(result.solid, result.bbox, result.components).kind


def test_elongated_flat_bottom_is_a_profile_shot(preset):
    array = canvas(600, 1200)
    array[380:480, 150:1050] = 60      # вытянутый силуэт с ровным низом
    array[300:380, 700:1000] = 60      # задник повыше

    assert kind_of(array, preset) == SIDE_OR_SOLE


def test_two_objects_are_a_pair(preset):
    array = canvas(700, 900)
    array[300:520, 100:420] = 60
    array[360:560, 480:800] = 60

    assert kind_of(array, preset) == PAIR


def test_symmetric_square_is_a_top_view(preset):
    array = canvas(1000, 700)
    array[200:900, 150:550] = 60

    assert kind_of(array, preset) == TOP


def test_labels_are_human_readable(preset):
    array = canvas(600, 1200)
    array[380:480, 150:1050] = 60
    background = estimate_background(array, preset.background.border_fraction)
    result = build_masks(array, background, preset.mask, preset.background.border_fraction)

    assert classify(result.solid, result.bbox, result.components).label
