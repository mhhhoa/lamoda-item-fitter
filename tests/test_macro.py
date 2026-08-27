"""Макро-кадры приводятся к холсту без правил полей.

У крупного плана товар намеренно выходит за край, габарита у него нет и
выравнивать нечего. Но размер обязан стать стандартным — иначе такой кадр
пришлось бы доводить руками.
"""

import pytest
from PIL import Image

from lamoda_item_fitter.fitter import PASSTHROUGH, fit_image, place_on_canvas
from lamoda_item_fitter.background import estimate_background
from tests.conftest import as_image, canvas

import numpy as np


def macro_frame(height, width, bleed="left", level=248):
    """Крупный план: тёмный объект уходит за указанный край."""
    array = canvas(height, width, level)
    boxes = {
        "left": (slice(height // 5, int(height * 0.85)), slice(0, int(width * 0.8))),
        "right": (slice(height // 5, int(height * 0.85)), slice(int(width * 0.2), width)),
        "top": (slice(0, int(height * 0.7)), slice(width // 6, int(width * 0.85))),
    }
    array[boxes[bleed]] = 45
    return array


SIZES = [(4000, 3000), (3000, 4000), (3800, 5000), (2200, 1524), (900, 1400)]


@pytest.mark.parametrize("height,width", SIZES, ids=[f"{w}x{h}" for h, w in SIZES])
def test_macro_is_brought_to_canvas(preset, height, width):
    result = fit_image(as_image(macro_frame(height, width)), preset)

    assert result.status == PASSTHROUGH, result.reason
    assert result.image.size == (preset.canvas.width, preset.canvas.height)


def test_macro_keeps_whole_frame_by_default(preset):
    """Режим «вписать целиком» ничего не теряет: поля добираются фоном."""
    source = as_image(macro_frame(3000, 4000, level=240))

    result = fit_image(source, preset)

    corner = result.image.getpixel((3, 3))
    assert corner == (240, 240, 240), "поля заливаются фоном исходника"


def test_cover_mode_fills_the_canvas(preset):
    array = macro_frame(3000, 4000, level=240)
    covering = preset.replace(cropped_fit_mode="cover")

    background = estimate_background(array, preset.background.border_fraction)
    contained = place_on_canvas(as_image(array), preset, background, "contain")
    covered = place_on_canvas(as_image(array), covering, background, "cover")

    assert contained.size == covered.size == (preset.canvas.width, preset.canvas.height)
    # при заполнении кадр растянут сильнее, поэтому тёмного в нём больше
    dark = lambda im: (np.asarray(im).mean(axis=2) < 120).mean()
    assert dark(covered) > dark(contained)


def test_macro_already_of_the_right_size_is_untouched(preset):
    source = as_image(macro_frame(preset.canvas.height, preset.canvas.width))

    result = fit_image(source, preset)

    assert result.status == PASSTHROUGH
    assert "размер уже верный" in result.reason
