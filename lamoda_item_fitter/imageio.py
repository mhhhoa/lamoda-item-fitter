"""Чтение и запись изображений."""

from __future__ import annotations

import io
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

from .config import OutputCfg

SUPPORTED_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".jpe", ".png", ".webp", ".tif", ".tiff", ".bmp"}
)

#: белый, на который сводится альфа-канал до того, как оценён фон кадра
ALPHA_MATTE = (255, 255, 255)

#: под этим ключом запоминается размер исходника до уменьшения при чтении
SOURCE_SIZE = "lif_source_size"

# Кодировщик JPEG складывает оптимизированные таблицы Хаффмана в один буфер.
# Штатных 64 КБ не хватает на детальный кадр 1524×2200, и запись падает с
# «broken data stream» — поднимаем предел до заведомо достаточного.
ImageFile.MAXBLOCK = max(getattr(ImageFile, "MAXBLOCK", 0), 8 * 1024 * 1024)


class UnreadableImage(Exception):
    """Файл не открывается как изображение — с понятным текстом для пользователя."""


def is_supported(path: Path | str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES


#: режимы с расширенным диапазоном — обычный convert() их обрезает
WIDE_RANGE_MODES = frozenset({"I", "I;16", "I;16B", "I;16L", "I;16N", "F"})


def _to_eight_bit(image: Image.Image) -> Image.Image:
    """Сжимает 16- и 32-битные кадры в 8 бит.

    Прямой convert("RGB") обрезал бы всё выше 255, и снимок ретушёра в 16 битах
    превратился бы в белый лист — товар на нём просто не нашёлся бы.
    """
    array = np.asarray(image).astype(np.float64)
    peak = float(array.max())
    if peak > 255:
        divisor = 65535.0 if peak <= 65535 else peak
        array = array * (255.0 / divisor)
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8), "L")


def _to_srgb(image: Image.Image) -> Image.Image:
    """Приводит кадр к sRGB, если у него зашит другой профиль (обычно AdobeRGB)."""
    icc = image.info.get("icc_profile")
    if not icc:
        return image
    try:
        from PIL import ImageCms

        source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if (ImageCms.getProfileDescription(source) or "").strip().lower().startswith("srgb"):
            return image
        target = ImageCms.createProfile("sRGB")
        return ImageCms.profileToProfile(image, source, target, outputMode="RGB")
    except Exception:
        # битый или неподдерживаемый профиль — лучше отдать кадр как есть
        return image


def load_image(path: Path | str, max_side: int | None = None) -> Image.Image:
    """Загружает кадр: разворот по EXIF, sRGB, RGB без альфы.

    `max_side` просит декодировать JPEG сразу уменьшенным. Для распознавания
    полное разрешение не нужно, а снимок на 27 мегапикселей иначе занимает
    сотни мегабайт в каждом рабочем процессе. Исходный размер запоминается:
    без него расчёт нужного увеличения считал бы по уменьшенной копии и
    отбраковывал бы годные кадры.
    """
    try:
        image = Image.open(path)
        original = image.size
        if max_side and max(original) > max_side:
            # draft гарантирует результат не меньше запроса по обеим сторонам,
            # поэтому просим размер, ужатый по длинной стороне: иначе для
            # широкого кадра декодер возьмёт лишний масштаб
            ratio = max_side / max(original)
            image.draft("RGB", (max(1, round(original[0] * ratio)),
                                max(1, round(original[1] * ratio))))
        image.load()
    except UnidentifiedImageError as error:
        raise UnreadableImage(
            "файл не является изображением или повреждён") from error
    except OSError as error:
        raise UnreadableImage(f"файл не читается — {error}") from error
    image = ImageOps.exif_transpose(image)
    if image.mode in WIDE_RANGE_MODES:
        image = _to_eight_bit(image)
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, ALPHA_MATTE)
        flat.paste(rgba, mask=rgba.split()[-1])
        flat.info = {k: v for k, v in image.info.items() if k == "icc_profile"}
        image = flat
    elif image.mode != "RGB":
        icc = image.info.get("icc_profile")
        image = image.convert("RGB")
        if icc:
            image.info["icc_profile"] = icc
    image = _to_srgb(image)
    image.info[SOURCE_SIZE] = original
    return image


def _encode(image: Image.Image, fmt: str, quality: int, cfg: OutputCfg) -> bytes:
    buffer = io.BytesIO()
    if fmt == "png":
        image.save(buffer, "PNG", optimize=cfg.png_optimize)
        return buffer.getvalue()
    try:
        image.save(buffer, "JPEG", quality=quality,
                   subsampling=cfg.jpeg_subsampling, optimize=True, progressive=False)
    except OSError:
        # даже с поднятым пределом буфер может не сойтись — отдать файл
        # важнее, чем сэкономить проценты веса на таблицах Хаффмана
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=quality,
                   subsampling=cfg.jpeg_subsampling, optimize=False, progressive=False)
    return buffer.getvalue()


def save_image(image: Image.Image, path: Path | str, cfg: OutputCfg) -> tuple[int, int]:
    """Сохраняет кадр, укладываясь в лимит веса. Возвращает (байты, качество).

    JPEG кодируется в память по лестнице качества и на диск пишется один раз —
    первым вариантом, который влез в лимит. Если не влез ни один, пишется самый
    лёгкий, а вызывающий код сообщает об этом пользователю.
    """
    path = Path(path)
    fmt = "png" if cfg.format.lower() == "png" else "jpeg"
    if fmt == "png":
        data, quality = _encode(image, fmt, 0, cfg), 0
    else:
        ladder = [q for q in cfg.quality_ladder if q <= cfg.jpeg_quality] or [cfg.jpeg_quality]
        data, quality = b"", ladder[-1]
        for candidate in ladder:
            data = _encode(image, fmt, candidate, cfg)
            quality = candidate
            if len(data) <= cfg.max_bytes:
                break
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return len(data), quality


def output_suffix(cfg: OutputCfg) -> str:
    return ".png" if cfg.format.lower() == "png" else ".jpg"
