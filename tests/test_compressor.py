import io

from PIL import Image

from app.core.compressor import Status, compress_bytes, compress_file
from app.core.settings import MODE_LOSSLESS, MODE_MANUAL, Settings


def encode_jpeg(image: Image.Image, quality: int = 97, **kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, subsampling=0, **kwargs)
    return buffer.getvalue()


def open_bytes(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


# ---------------------------------------------------------------------------
# Целевой вес
# ---------------------------------------------------------------------------

def test_smart_mode_hits_the_target(photo):
    raw = encode_jpeg(photo(1600, 2000))
    settings = Settings(target_mb=0.4, max_side_enabled=False)
    result = compress_bytes(raw, settings)
    assert result.status is Status.OK
    assert len(result.data) <= settings.target_bytes


def test_target_reached_by_downscaling_when_quality_is_not_enough(photo):
    raw = encode_jpeg(photo(2400, 3000))
    settings = Settings(target_mb=0.08, min_quality=75, max_side_enabled=False, min_side=100)
    result = compress_bytes(raw, settings)
    assert result.status is Status.OK
    assert len(result.data) <= settings.target_bytes
    assert result.width < 2400 and result.height < 3000


def test_downscale_stops_at_the_minimum_side(photo):
    raw = encode_jpeg(photo(2000, 2000))
    settings = Settings(
        target_mb=0.01, min_quality=60, max_side_enabled=False,
        min_side_enabled=True, min_side=1000,
    )
    result = compress_bytes(raw, settings)
    assert result.status is Status.TOO_BIG
    assert min(result.width, result.height) >= 1000


def test_manual_mode_ignores_the_limit(photo):
    raw = encode_jpeg(photo(1200, 1200))
    settings = Settings(mode=MODE_MANUAL, quality=95, target_mb=0.05, max_side_enabled=False)
    result = compress_bytes(raw, settings)
    assert result.quality == 95
    assert result.status is Status.TOO_BIG  # честно сообщаем, что в лимит не попали
    assert len(result.data) > settings.target_bytes


# ---------------------------------------------------------------------------
# Без потерь
# ---------------------------------------------------------------------------

def test_lossless_path_keeps_every_pixel(photo):
    original = photo(800, 800)
    raw = encode_jpeg(original)
    settings = Settings(target_mb=5.0, max_side_enabled=False)

    result = compress_bytes(raw, settings)

    assert result.status is Status.LOSSLESS
    assert len(result.data) < len(raw)
    assert open_bytes(result.data).tobytes() == open_bytes(raw).tobytes()


def test_lossless_path_is_skipped_when_a_resize_is_required(photo):
    raw = encode_jpeg(photo(3000, 3000))
    settings = Settings(target_mb=50.0, max_side_enabled=True, max_side=1000)
    result = compress_bytes(raw, settings)
    assert result.status is not Status.LOSSLESS
    assert max(result.width, result.height) == 1000


def test_lossless_mode_reports_when_it_cannot_fit(photo):
    raw = encode_jpeg(photo(2000, 2500))
    settings = Settings(mode=MODE_LOSSLESS, target_mb=0.2, max_side_enabled=False)

    result = compress_bytes(raw, settings)

    assert result.status is Status.TOO_BIG
    assert result.note  # объясняем, почему без потерь не получилось


def test_lossless_mode_admits_when_pixels_had_to_change(photo):
    """Разворот по EXIF переписывает кадр — «без потерь» тут обещать нельзя."""
    exif = Image.Exif()
    exif[274] = 6
    raw = encode_jpeg(photo(600, 800), exif=exif)

    result = compress_bytes(raw, Settings(mode=MODE_LOSSLESS, target_mb=20.0))

    assert result.status is Status.NOT_LOSSLESS
    assert "метаданн" in result.note or "EXIF" in result.note


def test_lossless_mode_keeps_resolution_untouched(photo):
    """Уменьшение — это потеря, поэтому лимит по стороне тут не действует."""
    raw = encode_jpeg(photo(2000, 2000))
    settings = Settings(mode=MODE_LOSSLESS, max_side_enabled=True, max_side=500,
                        target_mb=20.0)

    result = compress_bytes(raw, settings)

    assert (result.width, result.height) == (2000, 2000)


# ---------------------------------------------------------------------------
# Разрешение, формат, цвет
# ---------------------------------------------------------------------------

def test_max_side_is_applied(photo):
    raw = encode_jpeg(photo(3000, 1500))
    settings = Settings(max_side_enabled=True, max_side=1200, target_mb=5.0)
    result = compress_bytes(raw, settings)
    assert (result.width, result.height) == (1200, 600)


def test_png_with_alpha_becomes_jpeg_on_white(photo):
    source = photo(400, 400).convert("RGBA")
    source.putalpha(0)  # полностью прозрачная
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")

    settings = Settings(output_format="jpeg", target_mb=5.0, max_side_enabled=False)
    encoded = compress_bytes(buffer.getvalue(), settings)

    assert encoded.fmt == "jpeg"
    result = open_bytes(encoded.data)
    assert result.mode == "RGB"
    assert result.getpixel((10, 10)) == (255, 255, 255)


def test_auto_format_turns_heic_into_jpeg(photo):
    pillow_heif = __import__("pillow_heif")
    buffer = io.BytesIO()
    pillow_heif.from_pillow(photo(600, 600)).save(buffer, format="HEIF", quality=90)

    settings = Settings(output_format="auto", target_mb=5.0, max_side_enabled=False)
    assert compress_bytes(buffer.getvalue(), settings).fmt == "jpeg"


def test_exif_orientation_is_baked_into_the_pixels(photo):
    exif = Image.Exif()
    exif[274] = 6  # повёрнуто на 90°, как снимает телефон
    raw = encode_jpeg(photo(600, 1000), exif=exif)

    settings = Settings(target_mb=5.0, max_side_enabled=False, keep_metadata=False)
    result = compress_bytes(raw, settings)

    assert (result.width, result.height) == (1000, 600)
    assert open_bytes(result.data).getexif().get(274, 1) in (0, 1)


def test_metadata_is_dropped_by_default_and_kept_on_request(photo):
    exif = Image.Exif()
    exif[271] = "TestCamera"
    raw = encode_jpeg(photo(700, 700), exif=exif)

    stripped = compress_bytes(
        raw, Settings(target_mb=0.2, max_side_enabled=False, keep_metadata=False)
    )
    kept = compress_bytes(
        raw, Settings(target_mb=0.2, max_side_enabled=False, keep_metadata=True)
    )

    assert open_bytes(stripped.data).getexif().get(271) is None
    assert open_bytes(kept.data).getexif().get(271) == "TestCamera"


# ---------------------------------------------------------------------------
# Работа с файлами
# ---------------------------------------------------------------------------

def test_original_is_kept_when_recompression_would_inflate_it(tmp_path, photo):
    source = tmp_path / "noisy.png"
    photo(500, 500).save(source)
    destination = tmp_path / "out" / "noisy.png"

    settings = Settings(
        output_format="png", target_mb=5.0, max_side_enabled=False,
        copy_when_already_small=False,
    )
    result = compress_file(source, lambda extension: destination, settings)

    assert result.output_size <= source.stat().st_size
    assert destination.read_bytes() == source.read_bytes()


def test_files_already_within_the_limit_are_copied(tmp_path, photo):
    source = tmp_path / "small.jpg"
    source.write_bytes(encode_jpeg(photo(300, 300), quality=80))
    destination = tmp_path / "out" / "small.jpg"

    settings = Settings(target_mb=5.0, max_side_enabled=False, copy_when_already_small=True)
    result = compress_file(source, lambda extension: destination, settings)

    assert result.status is Status.COPIED
    assert destination.read_bytes() == source.read_bytes()


def test_skipping_returns_no_destination(tmp_path, photo):
    source = tmp_path / "photo.jpg"
    source.write_bytes(encode_jpeg(photo(400, 400)))

    result = compress_file(source, lambda extension: None, Settings())

    assert result.status is Status.SKIPPED
    assert result.destination is None


# ---------------------------------------------------------------------------
# Защита от известных поломок кодировщика и глубины цвета
# ---------------------------------------------------------------------------

def test_jpeg_is_written_even_when_the_huffman_buffer_is_too_small(monkeypatch, photo):
    """С optimize кодировщик собирает кадр в один буфер и падает, если тот мал."""
    from PIL import ImageFile

    from app.core import compressor

    monkeypatch.setattr(ImageFile, "MAXBLOCK", 1024)
    monkeypatch.setattr(compressor, "_MAXBLOCK_CEILING", 0)  # запретим и рост буфера

    data = compressor.encode(photo(900, 900), "jpeg", 97, Settings())

    assert open_bytes(data).size == (900, 900)


def test_sixteen_bit_image_does_not_turn_into_a_white_sheet():
    import struct

    side = 128
    gradient = b"".join(
        struct.pack("<H", int(index * 65535 / (side * side - 1)))
        for index in range(side * side)
    )
    source = Image.frombytes("I;16", (side, side), gradient)

    from app.core.compressor import prepare_image

    result = prepare_image(source, Settings(), "jpeg").convert("L")
    values = list(result.get_flattened_data())

    assert min(values) < 10 and max(values) > 245
    assert sum(value == 255 for value in values) / len(values) < 0.05


def test_broken_file_is_never_copied_into_the_output(tmp_path):
    """Пустышка или текст с расширением .jpg не должны уехать в выгрузку."""
    import pytest

    for name, content in (("empty.jpg", b""), ("notes.jpg", "текст".encode("utf-8"))):
        source = tmp_path / name
        source.write_bytes(content)
        destination = tmp_path / "out" / name

        with pytest.raises(Exception):
            compress_file(source, lambda extension: destination, Settings())

        assert not destination.exists()


def test_mislabelled_file_gets_the_extension_of_its_real_format(tmp_path, photo):
    """PNG с именем .jpg должен лечь на диск как .png, а не притворяться JPEG."""
    source = tmp_path / "lying.jpg"
    photo(300, 300).save(source, format="PNG")
    seen = {}

    def destination_for(extension):
        seen["extension"] = extension
        return tmp_path / "out" / f"lying{extension}"

    result = compress_file(source, destination_for, Settings(target_mb=5.0))

    assert seen["extension"] == ".png"
    assert result.destination.name == "lying.png"


def test_normal_extension_is_preserved_on_copy(tmp_path, photo):
    """А привычное .jpeg переименовывать в .jpg незачем — имена ищут по списку."""
    source = tmp_path / "front.jpeg"
    source.write_bytes(encode_jpeg(photo(300, 300), quality=80))

    result = compress_file(
        source, lambda extension: tmp_path / "out" / f"front{extension}",
        Settings(target_mb=5.0),
    )

    assert result.status is Status.COPIED
    assert result.destination.name == "front.jpeg"
