"""Чтение исходников в разных форматах и цветовых режимах."""

import io

import numpy as np
import pytest
from PIL import Image

from lamoda_item_fitter.fitter import FITTED, fit_image
from lamoda_item_fitter.imageio import load_image, save_image
from tests.conftest import canvas


def shoe(height=900, width=1400, level=246):
    array = canvas(height, width, level)
    array[500:700, 200:1100] = 60
    return array


@pytest.mark.parametrize("name,save", [
    ("прозрачный PNG", lambda a, p: Image.fromarray(
        np.dstack([a, np.where(a[:, :, :1] > 200, 0, 255).astype(np.uint8).squeeze()[..., None]
                   ]).astype(np.uint8), "RGBA").save(p)),
    ("оттенки серого", lambda a, p: Image.fromarray(a).convert("L").save(p)),
    ("CMYK", lambda a, p: Image.fromarray(a).convert("CMYK").save(p)),
    ("16 бит", lambda a, p: Image.fromarray(
        (a[:, :, 0].astype(np.uint32) * 257).astype(np.uint32)).save(p)),
])
def test_unusual_modes_are_readable(tmp_path, preset, name, save):
    path = tmp_path / "исходник.tiff"
    save(shoe(), path)

    result = fit_image(load_image(path), preset)

    assert result.status == FITTED, f"{name}: {result.reason}"
    assert result.metrics.margins["bottom"] == preset.margins.bottom


def test_exif_rotation_is_applied(tmp_path, preset):
    array = canvas(1400, 900)
    array[200:1100, 500:700] = 60
    image = Image.fromarray(array)
    exif = image.getexif()
    exif[274] = 6  # снимок лежит на боку
    path = tmp_path / "повёрнутый.jpg"
    image.save(path, exif=exif)

    loaded = load_image(path)

    assert loaded.size == (1400, 900), "кадр должен быть развёрнут по EXIF"


def test_empty_frame_is_reported(tmp_path, preset):
    path = tmp_path / "пустой.jpg"
    Image.fromarray(canvas(900, 1400, 249)).save(path)

    result = fit_image(load_image(path), preset)

    assert result.status != FITTED
    assert "не найден" in result.reason


def test_quality_drops_to_fit_the_weight_limit(tmp_path, preset):
    """Шумный кадр в качестве 100 весит больше лимита — качество должно уступить."""
    noisy = Image.fromarray(canvas(2200, 1524, noise=90, seed=3))
    limited = preset.output.__class__(**{**preset.output.__dict__, "max_bytes": 4_000_000})

    size, quality = save_image(noisy, tmp_path / "шум.jpg", limited)

    assert quality < preset.output.jpeg_quality
    assert size <= limited.max_bytes


def test_unreachable_limit_still_produces_a_file(tmp_path, preset):
    """Если не влезает ни один вариант, отдаём самый лёгкий, а не ничего."""
    noisy = Image.fromarray(canvas(2200, 1524, noise=90, seed=3))
    impossible = preset.output.__class__(**{**preset.output.__dict__, "max_bytes": 1000})

    size, quality = save_image(noisy, tmp_path / "шум.jpg", impossible)

    assert quality == preset.output.min_jpeg_quality
    assert (tmp_path / "шум.jpg").exists()
    assert size > impossible.max_bytes


def test_detailed_image_saves_without_choking(tmp_path, preset):
    """Кодировщик JPEG не должен спотыкаться о собственный буфер.

    Шумный кадр в качестве 100 не влезает в 5 МБ и проходит подбор целиком —
    заодно это проверка, что подбор не спотыкается на предельном материале.
    """
    noisy = Image.fromarray(canvas(2200, 1524, noise=90, seed=5))

    size, quality = save_image(noisy, tmp_path / "детальный.jpg", preset.output)

    assert 0 < size <= preset.output.max_bytes
    assert preset.output.min_jpeg_quality <= quality <= preset.output.jpeg_quality


@pytest.mark.parametrize("limit_mb", [1.0, 2.0, 3.5])
def test_any_limit_is_honoured(tmp_path, preset, limit_mb):
    """Любой вес, выставленный в настройках, должен выдерживаться."""
    noisy = Image.fromarray(canvas(2200, 1524, noise=90, seed=7))
    limit = int(limit_mb * 1024 * 1024)
    cfg = preset.output.__class__(**{**preset.output.__dict__, "max_bytes": limit})

    size, _ = save_image(noisy, tmp_path / f"{limit_mb}.jpg", cfg)

    assert size <= limit


def test_quality_is_the_highest_that_fits(tmp_path, preset):
    """Сжимаем ровно настолько, насколько нужно, и ни ступенью больше.

    Ступень выше выбранной обязана не влезать в лимит — иначе программа
    отдала бы кадр хуже, чем могла бы при том же весе.
    """
    noisy = Image.fromarray(canvas(2200, 1524, noise=90, seed=11))
    limit = 3 * 1024 * 1024
    cfg = preset.output.__class__(**{**preset.output.__dict__, "max_bytes": limit})

    size, quality = save_image(noisy, tmp_path / "подбор.jpg", cfg)
    assert size <= limit
    assert quality < preset.output.jpeg_quality

    buffer = io.BytesIO()
    noisy.save(buffer, "JPEG", quality=quality + 1,
               subsampling=cfg.jpeg_subsampling, optimize=True, progressive=False)
    assert len(buffer.getvalue()) > limit


def test_roomy_limit_keeps_top_quality(tmp_path, preset):
    """Когда вес не жмёт, качество не трогаем вовсе."""
    photo = Image.fromarray(canvas(2200, 1524, noise=4, seed=13))
    cfg = preset.output.__class__(**{**preset.output.__dict__, "max_bytes": 50 * 1024 * 1024})

    _, quality = save_image(photo, tmp_path / "просторно.jpg", cfg)

    assert quality == preset.output.jpeg_quality
