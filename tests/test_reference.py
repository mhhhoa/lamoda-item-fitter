"""Регрессия на эталонах Ламоды.

Это главный тест проекта: 19 фото в reference/ прошли модерацию маркетплейса,
и по ним выверен пресет. Если правка алгоритма ломает согласие с ними — она
неверна, какими бы стройными ни выглядели синтетические тесты.
"""

from pathlib import Path

import pytest

from lamoda_item_fitter.analyze import analyze_paths, collect
from tests.conftest import expected_bottom

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
        assert margins["bottom"] == expected_bottom(preset), path.name
        assert margins["left"] >= preset.margins.left, path.name
        assert margins["right"] >= preset.margins.right, path.name
        assert margins["top"] >= preset.margins.top, path.name
        # масштаб почти не меняется: геометрия совпадает с ручной работой Ламоды
        assert 0.85 <= result.metrics.scale <= 1.15, path.name
        checked += 1
    assert checked == 10


def _independent_edges(image, threshold: int = 6) -> dict[str, int]:
    """Меряет поля готового кадра, не пользуясь нашей же маской.

    Модерация Ламоды смотрит на результат своими глазами и своим порогом.
    Проверять себя тем же кодом, который и расставлял товар, бессмысленно:
    ошибка размещения так и останется незамеченной — ровно это и случилось
    с версиями до 1.5, где товар вставал ровно на линию и модерация
    браковала кадр за то, что он её «не касается».
    """
    import numpy as np

    array = np.asarray(image.convert("RGB")).astype(np.int16)
    border = np.concatenate([array[:40].reshape(-1, 3), array[-40:].reshape(-1, 3),
                             array[:, :40].reshape(-1, 3), array[:, -40:].reshape(-1, 3)])
    difference = np.abs(array - np.median(border, axis=0)).max(axis=2)
    rows = np.where((difference > threshold).any(axis=1))[0]
    cols = np.where((difference > threshold).any(axis=0))[0]
    height, width = array.shape[:2]
    return {"top": int(rows.min()), "bottom": int(height - 1 - rows.max()),
            "left": int(cols.min()), "right": int(width - 1 - cols.max())}


def test_result_touches_the_bottom_margin_like_moderated_photos():
    """Товар обязан заходить в нижний отступ, как у прошедших модерацию фото.

    Замер самих эталонов: нижнее поле 312…361 при медиане 347. Ровно 360 —
    единственный край этого распределения, и на практике проверка Ламоды
    читает такое размещение как зазор.
    """
    from lamoda_item_fitter.config import Preset
    from lamoda_item_fitter.fitter import FITTED as FITTED_STATUS
    from lamoda_item_fitter.fitter import fit_image
    from lamoda_item_fitter.imageio import load_image

    preset = Preset.load(Path(__file__).resolve().parent.parent / "presets" / "lamoda.json")
    checked = 0
    for path in sorted(REFERENCE.glob("*")):
        result = fit_image(load_image(path), preset)
        if result.status != FITTED_STATUS:
            continue
        checked += 1
        edges = _independent_edges(result.image)
        assert edges["bottom"] < preset.margins.bottom, f"{path.name}: не касается отступа"
        assert edges["bottom"] >= 300, f"{path.name}: зашёл в отступ слишком глубоко"
        for side in ("top", "left", "right"):
            assert edges[side] >= 200 - 1, f"{path.name}: поле {side} = {edges[side]}"
    assert checked >= 10
