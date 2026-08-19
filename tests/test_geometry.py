"""Главный инвариант: товар стоит ровно на нижней линии отступа."""

import pytest

from lamoda_item_fitter.fitter import FITTED, fit_image
from tests.conftest import as_image, canvas

CASES = [
    # описание, кадр, товар (высота, ширина, отступ сверху, отступ слева)
    ("вид сбоку, широкий", (900, 1400), (200, 900, 500, 200)),
    ("сапог, высокий", (2000, 1200), (1500, 400, 300, 400)),
    ("квадратный", (1000, 1000), (500, 500, 300, 250)),
    ("крупный исходник", (4000, 3000), (1200, 2400, 2000, 300)),
    ("мелкий исходник", (300, 400), (80, 260, 150, 70)),
    ("исходник уже нужного размера", (2200, 1524), (400, 1000, 1400, 260)),
    ("товар у нижнего края кадра", (800, 1000), (300, 700, 500, 150)),
    ("товар в углу кадра", (1200, 1600), (300, 800, 100, 60)),
]


@pytest.mark.parametrize("name,frame,item", CASES, ids=[c[0] for c in CASES])
def test_item_stands_on_baseline(preset, name, frame, item):
    array = canvas(*frame)
    height, width, top, left = item
    array[top:top + height, left:left + width] = 60

    result = fit_image(as_image(array), preset)

    assert result.status == FITTED, result.reason
    assert result.image.size == (preset.canvas.width, preset.canvas.height)

    margins = result.metrics.margins
    assert margins["bottom"] == preset.margins.bottom, "низ товара обязан лежать на линии"
    assert margins["top"] >= preset.margins.top
    assert margins["left"] >= preset.margins.left
    assert margins["right"] >= preset.margins.right
    # нечётная ширина товара на чётном холсте даёт неизбежный пиксель разницы
    assert abs(margins["left"] - margins["right"]) <= 2


def test_scale_fills_the_zone(preset):
    """Товар занимает рабочую зону целиком — как в эталонах Ламоды."""
    array = canvas(900, 1400)
    array[500:700, 200:1100] = 60

    result = fit_image(as_image(array), preset)

    margins = result.metrics.margins
    item_width = preset.canvas.width - margins["left"] - margins["right"]
    assert item_width >= preset.zone_width - 4


def test_background_tone_is_preserved(preset):
    """Поля заливаются цветом фона исходника, а не белым."""
    array = canvas(900, 1400, level=232)
    array[500:700, 200:1100] = 60

    result = fit_image(as_image(array), preset)

    corner = result.image.getpixel((5, 5))
    assert corner == (232, 232, 232)


def test_dark_background_is_reported(preset):
    array = canvas(900, 1400, level=200)
    array[500:700, 200:1100] = 60

    result = fit_image(as_image(array), preset)

    assert any("фон темнее" in w for w in result.warnings)


def test_upscale_is_reported(preset):
    array = canvas(300, 400)
    array[150:230, 70:330] = 60

    result = fit_image(as_image(array), preset)

    assert result.metrics.scale > 1.0
    assert any("увеличен" in w for w in result.warnings)


def test_noisy_background_still_lands_on_baseline(preset):
    array = canvas(1200, 1600, noise=4)
    array[700:1000, 300:1300] = 60

    result = fit_image(as_image(array), preset)

    assert result.status == FITTED
    assert result.metrics.margins["bottom"] == preset.margins.bottom
