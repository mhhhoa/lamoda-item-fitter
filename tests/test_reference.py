"""Регрессия на эталонах Ламоды.

Это главный тест проекта: 19 фото в reference/ прошли модерацию маркетплейса,
и по ним выверен пресет. Если правка алгоритма ломает согласие с ними — она
неверна, какими бы стройными ни выглядели синтетические тесты.
"""

from pathlib import Path

import pytest

from lamoda_item_fitter.analyze import analyze_paths, collect

REFERENCE = Path(__file__).resolve().parent.parent / "reference"
pytestmark = pytest.mark.skipif(not list(REFERENCE.glob("*")), reason="эталоны не приложены")


@pytest.fixture(scope="module")
def measured():
    from lamoda_item_fitter.config import Preset

    preset = Preset.load(Path(__file__).resolve().parent.parent / "presets" / "lamoda.json")
    return analyze_paths(collect(REFERENCE), preset)


def test_every_reference_uses_the_declared_canvas(measured):
    items, summary = measured
    assert summary["files"] == 19
    assert summary["canvas_matches"] == summary["files"]


def test_background_is_flat_and_not_pure_white(measured):
    """Эталоны Ламоды сняты на ровный фон 249, а не на чистый белый."""
    items, summary = measured
    assert summary["backgrounds"] == [(249, 249, 249)]
    assert summary["background_spread"]["max"] == 0.0


def test_half_of_the_gallery_is_macro(measured):
    """Почти половина опубликованных кадров намеренно выходит за края."""
    items, summary = measured
    assert summary["fitted"] == 10
    assert summary["cropped"] == 9


def test_bottom_margin_matches_the_rule(measured):
    items, summary = measured
    bottom = summary["margin_bottom"]
    assert 320 <= bottom["median"] <= 365
    assert bottom["max"] <= 365, "ни один эталон не висит выше линии отступа"
    assert bottom["min"] >= 300


def test_side_margins_match_the_rule(measured):
    items, summary = measured
    for key in ("margin_left", "margin_right"):
        assert 150 <= summary[key]["median"] <= 215


def test_item_always_fills_the_zone_width(measured):
    """Ключевой вывод: масштаб везде задаёт ширина, коэффициенты по ракурсам не нужны."""
    items, summary = measured
    assert summary["width_limited"] == summary["fitted"]
    assert 0.95 <= summary["fill_width"]["median"] <= 1.10
    assert summary["fill_width"]["min"] >= 0.95


def test_item_is_centred_horizontally(measured):
    items, summary = measured
    assert abs(summary["center_offset"]["median"]) <= 40


def test_scale_is_not_normalised_across_angles(measured):
    """Ламода не согласовывает масштаб между ракурсами одного артикула."""
    items, summary = measured
    heights = [m.fill_height for m in items if m.fitted]
    assert max(heights) / min(heights) > 2.0


def test_refitting_a_published_photo_reproduces_the_rules(preset):
    """Прогон уже опубликованного фото через программу обязан дать точную сетку.

    Ламода выравнивает вручную и попадает в 312–360 по низу и 124–209 по краям;
    после нашей подгонки те же кадры встают ровно в 360 и не ближе 200 к краю.
    """
    from lamoda_item_fitter.analyze import measure_file
    from lamoda_item_fitter.fitter import FITTED, fit_image
    from lamoda_item_fitter.imageio import load_image

    checked = 0
    for path in sorted(REFERENCE.glob("*.webp")):
        measured = measure_file(path, preset)
        if measured is None or not measured.fitted:
            continue
        result = fit_image(load_image(path), preset)
        assert result.status == FITTED, f"{path.name}: {result.reason}"
        margins = result.metrics.margins
        assert margins["bottom"] == preset.margins.bottom, path.name
        assert margins["left"] >= preset.margins.left, path.name
        assert margins["right"] >= preset.margins.right, path.name
        assert margins["top"] >= preset.margins.top, path.name
        # масштаб почти не меняется: геометрия совпадает с ручной работой Ламоды
        assert 0.85 <= result.metrics.scale <= 1.15, path.name
        checked += 1
    assert checked == 10
