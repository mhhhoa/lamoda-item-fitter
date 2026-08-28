"""Точный размер кадра: обрезка, поля, якоря, увеличение."""

import io

from PIL import Image

from app.core.compressor import Status, apply_exact_size, compress_bytes
from app.core.settings import (
    FIT_CONTAIN,
    FIT_COVER,
    FIT_STRETCH,
    PAD_BLACK,
    PAD_EDGE,
    SHARPEN_OFF,
    SHARPEN_STRONG,
    Settings,
)


def encode_jpeg(image: Image.Image, quality: int = 95) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def exact(width: int = 1000, height: int = 1500, **overrides) -> Settings:
    overrides.setdefault("target_mb", 20.0)
    return Settings(
        exact_size_enabled=True, exact_width=width, exact_height=height, **overrides
    )


# ---------------------------------------------------------------------------
# Размер на выходе
# ---------------------------------------------------------------------------

def test_every_fit_mode_gives_exactly_the_requested_pixels(photo):
    sources = {
        "горизонталь": encode_jpeg(photo(1800, 1200)),
        "вертикаль": encode_jpeg(photo(1200, 1800)),
        "квадрат": encode_jpeg(photo(1400, 1400)),
    }
    for mode in (FIT_COVER, FIT_CONTAIN, FIT_STRETCH):
        for name, raw in sources.items():
            result = compress_bytes(raw, exact(fit_mode=mode))
            assert (result.width, result.height) == (1000, 1500), f"{mode} / {name}"


def test_exact_size_wins_over_the_long_side_limit(photo):
    raw = encode_jpeg(photo(1800, 1200))
    settings = exact(max_side_enabled=True, max_side=400)

    result = compress_bytes(raw, settings)

    assert (result.width, result.height) == (1000, 1500)


# ---------------------------------------------------------------------------
# Обрезка и якоря
# ---------------------------------------------------------------------------

def _marked_image(photo):
    """Кадр с цветными метками по краям — по ним видно, что осталось."""
    image = photo(1800, 1200).convert("RGB")
    image.paste(Image.new("RGB", (300, 1200), (255, 0, 0)), (0, 0))
    image.paste(Image.new("RGB", (300, 1200), (0, 0, 255)), (1500, 0))
    return image


def test_crop_anchor_decides_which_side_survives(photo):
    """Из горизонтали в вертикаль срезаются бока — якорь выбирает какие."""
    marked = _marked_image(photo)

    def edges(anchor: str):
        result = compress_bytes(
            encode_jpeg(marked, 98), exact(fit_mode=FIT_COVER, crop_anchor=anchor)
        )
        canvas = Image.open(io.BytesIO(result.data))
        return canvas.getpixel((6, 750)), canvas.getpixel((993, 750))

    left_kept, left_dropped = edges("left")
    right_dropped, right_kept = edges("right")

    # Прижали влево — уцелела красная метка, синяя ушла под нож.
    assert left_kept[0] > 180 and left_kept[2] < 80, left_kept
    assert left_dropped[2] < 180, left_dropped
    # Прижали вправо — наоборот.
    assert right_kept[2] > 180 and right_kept[0] < 80, right_kept
    assert right_dropped[0] < 180, right_dropped


def test_contain_keeps_the_whole_frame_and_fills_the_rest(photo):
    marked = _marked_image(photo)

    result = compress_bytes(encode_jpeg(marked, 98), exact(fit_mode=FIT_CONTAIN))
    canvas = Image.open(io.BytesIO(result.data))

    assert canvas.size == (1000, 1500)
    # Обе метки на месте: ничего не срезали.
    assert canvas.getpixel((6, 750))[0] > 180
    assert canvas.getpixel((993, 750))[2] > 180
    # Сверху и снизу — белые поля.
    assert canvas.getpixel((500, 5)) == (255, 255, 255)
    assert canvas.getpixel((500, 1494)) == (255, 255, 255)


def test_padding_colour_follows_the_setting(photo):
    raw = encode_jpeg(photo(1800, 1200))

    black = compress_bytes(raw, exact(fit_mode=FIT_CONTAIN, pad_mode=PAD_BLACK))
    edge = compress_bytes(raw, exact(fit_mode=FIT_CONTAIN, pad_mode=PAD_EDGE))

    assert Image.open(io.BytesIO(black.data)).getpixel((500, 5)) == (0, 0, 0)
    assert Image.open(io.BytesIO(edge.data)).getpixel((500, 5)) not in ((0, 0, 0), (255, 255, 255))


# ---------------------------------------------------------------------------
# Увеличение
# ---------------------------------------------------------------------------

def test_upscaling_is_announced_not_hidden(photo):
    result = compress_bytes(encode_jpeg(photo(400, 600)), exact(allow_upscale=True))

    assert (result.width, result.height) == (1000, 1500)
    assert "увеличено" in result.note


def test_refusing_to_upscale_still_gives_the_exact_frame(photo):
    """Обещание точного размера остаётся, но фото в нём меньше — и это видно."""
    result = compress_bytes(encode_jpeg(photo(400, 600)), exact(allow_upscale=False))

    canvas = Image.open(io.BytesIO(result.data))
    assert canvas.size == (1000, 1500)
    assert "меньше заданного" in result.note
    assert canvas.getpixel((5, 5)) == (255, 255, 255)


def test_exact_size_cannot_shrink_to_reach_the_weight_limit(photo):
    """Уменьшать нельзя — программа объясняет, что крутить вместо этого."""
    settings = exact(2400, 3200, target_mb=0.05, min_quality=88)

    result = compress_bytes(encode_jpeg(photo(2400, 3200)), settings)

    assert result.status is Status.TOO_BIG
    assert (result.width, result.height) == (2400, 3200)
    assert "качества" in result.note


# ---------------------------------------------------------------------------
# Резкость
# ---------------------------------------------------------------------------

def test_sharpening_only_touches_shrunk_frames(photo):
    source = photo(1200, 1200)

    same = apply_exact_size(source, exact(1200, 1200, sharpen=SHARPEN_STRONG), "jpeg")[0]
    assert same.tobytes() == source.tobytes()


def test_sharpening_changes_the_result_when_shrinking(photo):
    raw = encode_jpeg(photo(1600, 1600))
    plain = compress_bytes(raw, Settings(max_side=600, sharpen=SHARPEN_OFF, target_mb=20.0))
    sharp = compress_bytes(raw, Settings(max_side=600, sharpen=SHARPEN_STRONG, target_mb=20.0))

    assert (plain.width, plain.height) == (sharp.width, sharp.height) == (600, 600)
    assert plain.data != sharp.data
