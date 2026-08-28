"""Ядро сжатия: всё, что связано с картинками, и ничего про интерфейс.

Модуль намеренно не зависит от Qt — его можно дёргать из тестов и из
консоли, а окно приложения просто вызывает `compress_file`.
"""

from __future__ import annotations

import io
import math
import shutil
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PIL import Image, ImageCms, ImageFile, ImageFilter, ImageOps

from .settings import (
    FIT_COVER,
    FIT_STRETCH,
    LOSSY_FORMATS,
    MODE_LOSSLESS,
    MODE_MANUAL,
    MODE_SMART,
    OUTPUT_FORMATS,
    PAD_BLACK,
    PAD_CUSTOM,
    PAD_EDGE,
    PAD_TRANSPARENT,
    SHARPEN_OFF,
    Settings,
)

try:  # HEIC/HEIF с айфонов
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE, HEIF_ERROR = True, ""
except Exception as _error:  # pragma: no cover - зависит от сборки
    HEIF_AVAILABLE, HEIF_ERROR = False, repr(_error)

try:  # честная lossless-оптимизация JPEG
    import mozjpeg_lossless_optimization as mozjpeg

    MOZJPEG_AVAILABLE, MOZJPEG_ERROR = True, ""
except Exception as _error:  # pragma: no cover - зависит от сборки
    MOZJPEG_AVAILABLE, MOZJPEG_ERROR = False, repr(_error)

# Фотографии с современных камер легко перешагивают дефолтный лимит Pillow,
# а «бомбу» в 512 Мпикс в папке с товарными съёмками ждать не приходится.
Image.MAX_IMAGE_PIXELS = 512_000_000

#: Чем заливаем прозрачность при переводе в формат без альфы.
FLATTEN_BACKGROUND = (255, 255, 255)

#: Сколько раз готовы уменьшать картинку, прежде чем признать поражение.
MAX_DOWNSCALE_STEPS = 12


class Status(str, Enum):
    OK = "ok"                # пережали, уложились
    LOSSLESS = "lossless"    # уложились совсем без потерь
    COPIED = "copied"        # уже подходил, скопировали как есть
    NOT_LOSSLESS = "not_lossless"  # без потерь не вышло, сохранён на максимуме
    TOO_BIG = "too_big"      # сжали как смогли, но в лимит не влезли
    SKIPPED = "skipped"      # ничего не делали
    ERROR = "error"


@dataclass
class Result:
    status: Status
    source: Path
    destination: Path | None = None
    source_size: int = 0
    output_size: int = 0
    width: int = 0
    height: int = 0
    quality: int | None = None
    scale: float = 1.0
    message: str = ""

    @property
    def saved_bytes(self) -> int:
        return max(0, self.source_size - self.output_size)

    @property
    def ratio(self) -> float:
        if not self.source_size:
            return 0.0
        return self.output_size / self.source_size


@dataclass
class Encoded:
    """Что получилось на выходе кодировщика, до записи на диск."""

    data: bytes
    fmt: str
    status: Status
    width: int
    height: int
    quality: int | None = None
    scale: float = 1.0
    note: str = ""


class Cancelled(Exception):
    """Пользователь нажал «Стоп»."""


# ---------------------------------------------------------------------------
# Подготовка изображения
# ---------------------------------------------------------------------------

def _pillow_format(fmt_key: str) -> str:
    return {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "avif": "AVIF"}[fmt_key]


def resolve_output_format(settings: Settings, source_format: str | None) -> str:
    """Во что сохраняем конкретный файл с учётом режима «как в оригинале»."""
    if settings.output_format != "auto":
        return settings.output_format
    src = (source_format or "").lower()
    if src in {"jpeg", "mpo"}:
        return "jpeg"
    if src == "png":
        return "png"
    if src == "webp":
        return "webp"
    if src == "avif":
        return "avif"
    # HEIC, TIFF, BMP и прочее браузеры и маркетплейсы не любят — в JPEG.
    return "jpeg"


def output_extension(fmt_key: str) -> str:
    return OUTPUT_FORMATS[fmt_key][1] or ".jpg"


def _is_srgb(profile_bytes: bytes) -> bool:
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(profile_bytes))
        description = (ImageCms.getProfileDescription(profile) or "").lower()
    except Exception:
        return False
    return "srgb" in description


def _to_srgb(image: Image.Image) -> Image.Image:
    """Переводит картинку в sRGB, если в ней зашит другой профиль.

    Без этого снимки в Adobe RGB на сайте выглядят блёкло — маркетплейс
    показывает их как sRGB, не читая профиль.
    """
    profile_bytes = image.info.get("icc_profile")
    if not profile_bytes or _is_srgb(profile_bytes):
        return image
    try:
        source = ImageCms.ImageCmsProfile(io.BytesIO(profile_bytes))
        target = ImageCms.createProfile("sRGB")
        mode = "RGBA" if image.mode in ("RGBA", "LA", "PA") else "RGB"
        converted = ImageCms.profileToProfile(image, source, target, outputMode=mode)
    except Exception:
        return image
    if converted is None:
        return image
    converted.info.pop("icc_profile", None)
    return converted


def _flatten(image: Image.Image) -> Image.Image:
    """Убирает альфу, подкладывая белый фон."""
    if image.mode not in ("RGBA", "LA", "PA") and "transparency" not in image.info:
        return image
    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, FLATTEN_BACKGROUND)
    background.paste(rgba, mask=rgba.split()[-1])
    return background


def pixel_changing_step(image: Image.Image, settings: Settings, target_format: str) -> str:
    """Называет преобразование, которое изменит пиксели, либо пустую строку.

    Нужно, чтобы не обещать «без потерь» там, где кадр всё-таки переписан:
    развёрнут по EXIF, пересчитан в sRGB или лишён прозрачности.
    """
    if image.getexif().get(274, 1) not in (0, 1):
        return "разворот по EXIF"

    icc = image.info.get("icc_profile")
    if settings.convert_to_srgb and icc and not _is_srgb(icc):
        return "пересчёт цвета в sRGB"

    supports_alpha = target_format in {"png", "webp", "avif"}
    has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
    if has_alpha and not supports_alpha:
        return "заливка прозрачности белым"

    if image.mode not in ("RGB", "RGBA", "L", "LA"):
        return f"смена цветовой модели ({image.mode})"
    return ""


def prepare_image(image: Image.Image, settings: Settings, target_format: str) -> Image.Image:
    """Разворачивает по EXIF, приводит цвет и режим к пригодному для записи."""
    image = ImageOps.exif_transpose(image) or image

    if settings.convert_to_srgb:
        image = _to_srgb(image)

    supports_alpha = target_format in {"png", "webp", "avif"}
    if not supports_alpha:
        image = _flatten(image)

    if image.mode in ("P", "PA"):
        image = image.convert("RGBA" if supports_alpha else "RGB")
    if image.mode == "CMYK":
        image = image.convert("RGB")
    if image.mode.startswith("I") or image.mode == "F":
        image = _to_eight_bits(image)
    if image.mode == "LA" and not supports_alpha:
        image = image.convert("L")
    if image.mode not in ("RGB", "RGBA", "L", "LA"):
        image = image.convert("RGBA" if supports_alpha else "RGB")
    return image


def _to_eight_bits(image: Image.Image) -> Image.Image:
    """Сводит 16- и 32-битный кадр к восьми битам, не выжигая света.

    Обычный convert("L") обрезает всё выше 255, и снимок ретушёра в 16 битах
    превращается в белый лист. Делим по номинальному диапазону, а не по пику:
    нормировка по максимуму меняла бы экспозицию снимка.
    """
    source = image.convert("I")
    try:
        highest = source.getextrema()[1]
    except (ValueError, TypeError):
        highest = 65535
    if not highest or highest <= 255:
        return source.convert("L")
    divisor = 257.0 if highest <= 65535 else highest / 255.0
    return source.point(lambda value: value / divisor, "L")


def fit_within(image: Image.Image, max_side: int | None, settings: Settings) -> Image.Image:
    """Ужимает по длинной стороне, если она больше лимита."""
    if not max_side or max(image.size) <= max_side:
        return image
    scale = max_side / max(image.size)
    return _scaled(image, scale, settings)


#: Насколько подчёркивать детали после уменьшения. Радиус подобран так,
#: чтобы не рисовать ореолы по контуру товара.
SHARPEN_PRESETS = {
    "light": (0.8, 55, 3),
    "strong": (1.1, 110, 2),
}


def _resized(image: Image.Image, size: tuple[int, int], settings: Settings) -> Image.Image:
    """Меняет размер и, если кадр уменьшился, возвращает ему резкость.

    Любое уменьшение усредняет соседние пиксели, и фактура ткани заметно
    мылится. Аккуратный unsharp возвращает её, не рисуя ореолов.
    """
    if size == image.size:
        return image
    result = image.resize(size, Image.LANCZOS)
    shrunk = size[0] * size[1] < image.width * image.height
    preset = SHARPEN_PRESETS.get(settings.sharpen)
    if shrunk and settings.sharpen != SHARPEN_OFF and preset:
        radius, percent, threshold = preset
        result = result.filter(
            ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold)
        )
    return result


def _scaled(image: Image.Image, scale: float, settings: Settings) -> Image.Image:
    if scale >= 1.0:
        return image
    width = max(1, int(round(image.width * scale)))
    height = max(1, int(round(image.height * scale)))
    return _resized(image, (width, height), settings)


# ---------------------------------------------------------------------------
# Точный размер кадра
# ---------------------------------------------------------------------------

def _anchor_offset(space: int, anchor: str, axis: str) -> int:
    """Смещение кадра внутри холста.

    `space` отрицателен, когда фотография больше холста, — тогда та же
    формула даёт координату обрезки, и один код обслуживает оба случая.
    """
    if axis == "x":
        if anchor.endswith("left"):
            return 0
        if anchor.endswith("right"):
            return space
    else:
        if anchor.startswith("top"):
            return 0
        if anchor.startswith("bottom"):
            return space
    return space // 2


def _edge_color(image: Image.Image) -> tuple[int, int, int]:
    """Усреднённый цвет по краям кадра — им заливаются поля."""
    probe = image.convert("RGB").resize((3, 3), Image.BOX)
    pixels = [probe.getpixel((x, y)) for x in range(3) for y in range(3) if (x, y) != (1, 1)]
    count = len(pixels)
    return tuple(sum(channel[i] for channel in pixels) // count for i in range(3))


def _pad_background(image: Image.Image, settings: Settings, supports_alpha: bool):
    if settings.pad_mode == PAD_TRANSPARENT and supports_alpha:
        return (0, 0, 0, 0)
    if settings.pad_mode == PAD_BLACK:
        base = (0, 0, 0)
    elif settings.pad_mode == PAD_EDGE:
        base = _edge_color(image)
    elif settings.pad_mode == PAD_CUSTOM:
        text = settings.pad_color.lstrip("#")
        try:
            base = tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
        except (ValueError, IndexError):
            base = FLATTEN_BACKGROUND
    else:
        base = FLATTEN_BACKGROUND
    return base + (255,) if supports_alpha else base


def apply_exact_size(
    image: Image.Image, settings: Settings, target_format: str
) -> tuple[Image.Image, str]:
    """Приводит кадр ровно к заданным пикселям.

    Вторым значением возвращает пояснение для строки списка: увеличение
    и подкладку полей пользователь должен видеть, а не обнаруживать потом
    в готовых файлах.
    """
    source_size = image.size
    target = (settings.exact_width, settings.exact_height)

    if settings.fit_mode == FIT_STRETCH:
        # Растянуть — значит выдать ровно заданный кадр, на то и режим.
        note = _grow_note(source_size, target) if _grows(source_size, target) else ""
        return _resized(image, target, settings), note

    by_width = target[0] / image.width
    by_height = target[1] / image.height
    scale = max(by_width, by_height) if settings.fit_mode == FIT_COVER else min(by_width, by_height)

    note = ""
    if scale > 1.0:
        if settings.allow_upscale:
            note = _grow_note(source_size, target)
        else:
            # Увеличивать запретили — отдаём заданный кадр, но честно
            # говорим, что фотография в нём меньше и вокруг поля.
            scale = 1.0
            note = f"исходник меньше заданного ({source_size[0]}×{source_size[1]}), добавлены поля"

    fitted = _resized(
        image,
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        settings,
    )

    supports_alpha = target_format in {"png", "webp", "avif"}
    background = _pad_background(fitted, settings, supports_alpha)
    mode = "RGBA" if supports_alpha and len(background) == 4 else "RGB"
    if fitted.mode != mode:
        fitted = fitted.convert(mode)

    canvas = Image.new(mode, target, background)
    canvas.paste(
        fitted,
        (
            _anchor_offset(target[0] - fitted.width, settings.crop_anchor, "x"),
            _anchor_offset(target[1] - fitted.height, settings.crop_anchor, "y"),
        ),
    )
    return canvas, note


def _grows(source: tuple[int, int], target: tuple[int, int]) -> bool:
    return target[0] > source[0] or target[1] > source[1]


def _grow_note(source: tuple[int, int], target: tuple[int, int]) -> str:
    return f"увеличено с {source[0]}×{source[1]}"


# ---------------------------------------------------------------------------
# Кодирование
# ---------------------------------------------------------------------------

def _subsampling(settings: Settings, quality: int) -> int:
    if settings.subsampling == "444":
        return 0
    if settings.subsampling == "422":
        return 1
    if settings.subsampling == "420":
        return 2
    # Авто: на высоком качестве бережём цвет, ниже — экономим вес.
    return 0 if quality >= 90 else 2


def _metadata_kwargs(image: Image.Image, settings: Settings) -> dict:
    if not settings.keep_metadata:
        return {}
    kwargs: dict = {}
    exif = image.info.get("exif")
    if exif:
        kwargs["exif"] = exif
    icc = image.info.get("icc_profile")
    if icc:
        kwargs["icc_profile"] = icc
    return kwargs


def encode(
    image: Image.Image,
    fmt: str,
    quality: int,
    settings: Settings,
    *,
    lossless: bool = False,
    fast: bool = False,
) -> bytes:
    """Пишет картинку в память и возвращает готовые байты файла.

    `fast` включает более дешёвый проход упаковки — он нужен во время
    подбора параметров. Итоговый файл всегда пишется на полных настройках,
    а они дают результат не больше быстрого, так что подбор остаётся
    корректным.
    """
    buffer = io.BytesIO()
    kwargs = _metadata_kwargs(image, settings)

    if fmt == "jpeg":
        # У JPEG дешёвого прохода нет: optimize и mozjpeg стоят копейки,
        # зато без них оценка веса разъезжается с итоговым файлом.
        _save_jpeg(
            image,
            buffer,
            quality=quality,
            optimize=True,
            progressive=settings.progressive,
            subsampling=_subsampling(settings, quality),
            **kwargs,
        )
        return _mozjpeg_pass(buffer.getvalue(), settings)

    if fmt == "png":
        image.save(
            buffer, format="PNG", optimize=not fast,
            compress_level=6 if fast else 9, **kwargs,
        )
        return buffer.getvalue()

    if fmt == "webp":
        if lossless:
            image.save(buffer, format="WEBP", lossless=True, method=3 if fast else 6, **kwargs)
        else:
            image.save(buffer, format="WEBP", quality=quality, method=3 if fast else 5, **kwargs)
        return buffer.getvalue()

    if fmt == "avif":
        image.save(buffer, format="AVIF", quality=quality, speed=9 if fast else 6, **kwargs)
        return buffer.getvalue()

    raise ValueError(f"Неизвестный формат вывода: {fmt}")


def finalize(attempt: "_Attempt", fmt: str, settings: Settings) -> bytes:
    """Перезаписывает найденный вариант на полных настройках упаковки."""
    if fmt == "jpeg":
        return attempt.data
    quality = attempt.quality if attempt.quality is not None else settings.quality
    full = encode(attempt.image, fmt, quality, settings)
    return full if len(full) <= len(attempt.data) else attempt.data


#: MAXBLOCK — глобальная величина Pillow, поэтому поднимаем её под замком
#: и только вверх: увеличенный буфер соседним потокам не мешает.
_MAXBLOCK_LOCK = threading.Lock()
_MAXBLOCK_CEILING = 128 * 1024 * 1024


def _raise_maxblock(needed: int) -> None:
    with _MAXBLOCK_LOCK:
        if ImageFile.MAXBLOCK < needed <= _MAXBLOCK_CEILING:
            ImageFile.MAXBLOCK = needed


def _save_jpeg(image: Image.Image, buffer: io.BytesIO, **params) -> None:
    """Записывает JPEG, обходя нехватку буфера таблиц Хаффмана.

    С optimize кодировщик собирает весь кадр в один буфер, и на детальном
    снимке штатного размера не хватает — save падает с «broken data stream».
    Поднимаем буфер, а если и это не помогло, пишем без оптимизации:
    отдать файл важнее, чем сэкономить проценты веса.
    """
    attempts = (
        params,
        params,  # тот же вызов, но уже с увеличенным буфером
        {**params, "optimize": False, "progressive": False},
    )
    for index, attempt in enumerate(attempts):
        try:
            image.save(buffer, format="JPEG", **attempt)
            return
        except OSError:
            if index == len(attempts) - 1:
                raise
            buffer.seek(0)
            buffer.truncate()
            if index == 0:
                _raise_maxblock(image.width * image.height * 4 + 65536)


def _mozjpeg_pass(data: bytes, settings: Settings) -> bytes:
    """Дожимает готовый JPEG без единого изменения пикселей.

    Это перестроение таблиц Хаффмана — те же 8x8 блоки, но записанные
    компактнее. Даёт стабильные 5–15% и никогда не портит картинку.
    """
    if not MOZJPEG_AVAILABLE:
        return data
    markers = mozjpeg.COPY_MARKERS.ALL if settings.keep_metadata else mozjpeg.COPY_MARKERS.NONE
    try:
        optimized = mozjpeg.optimize(data, markers)
    except Exception:
        return data
    return optimized if len(optimized) < len(data) else data


# ---------------------------------------------------------------------------
# Подбор параметров под целевой вес
# ---------------------------------------------------------------------------

@dataclass
class _Attempt:
    data: bytes
    quality: int | None
    scale: float
    image: Image.Image


def _search_quality(
    image: Image.Image,
    fmt: str,
    settings: Settings,
    target: int,
    scale: float,
    check_cancel,
) -> _Attempt | None:
    """Наибольшее качество, при котором файл влезает в лимит.

    Возвращает None, если не влезает даже на минимальном качестве.
    """
    high, low = settings.quality, settings.min_quality
    check_cancel()

    best_high = encode(image, fmt, high, settings, fast=True)
    if len(best_high) <= target:
        return _Attempt(best_high, high, scale, image)

    check_cancel()
    lowest = encode(image, fmt, low, settings, fast=True)
    if len(lowest) > target:
        return None

    best = _Attempt(lowest, low, scale, image)
    # Шагов ровно столько, сколько нужно, чтобы сузить диапазон до единицы.
    steps = max(0, math.ceil(math.log2(high - low))) if high > low else 0
    for _ in range(steps):
        if high - low <= 1:
            break
        middle = (high + low) // 2
        check_cancel()
        data = encode(image, fmt, middle, settings, fast=True)
        if len(data) <= target:
            best = _Attempt(data, middle, scale, image)
            low = middle
        else:
            high = middle
    return best


def _search_scale(
    image: Image.Image,
    fmt: str,
    settings: Settings,
    target: int,
    check_cancel,
) -> _Attempt:
    """Уменьшает картинку, пока она не влезет в лимит.

    Первый шаг считаем по площади: вес JPEG примерно пропорционален числу
    пикселей, поэтому sqrt(target / current) — хорошая стартовая догадка,
    и обычно хватает одной-двух проверок вместо десятка.
    """
    lossy = fmt in LOSSY_FORMATS
    probe_quality = settings.min_quality if lossy else settings.quality
    check_cancel()
    reference = encode(image, fmt, probe_quality, settings, fast=True)
    best = _Attempt(reference, probe_quality if lossy else None, 1.0, image)

    min_side = settings.min_side if settings.min_side_enabled else 1
    scale = min(0.98, math.sqrt(target / len(reference)) * 0.97)

    # Оценка может уехать ниже разрешённого минимума. Тогда пробуем ровно
    # тот предел, который разрешён: даже если в лимит не влезем, отдать
    # уменьшенный файл честнее, чем вернуть исходный размер.
    smallest_allowed = min_side / min(image.size) if min_side > 1 else 0.02
    scale = max(scale, min(0.98, smallest_allowed))

    for _ in range(MAX_DOWNSCALE_STEPS):
        check_cancel()
        candidate = _scaled(image, scale, settings)
        if min(candidate.size) < min_side:
            break
        if lossy:
            attempt = _search_quality(candidate, fmt, settings, target, scale, check_cancel)
            if attempt is not None:
                return attempt
            data = encode(candidate, fmt, settings.min_quality, settings, fast=True)
            attempt = _Attempt(data, settings.min_quality, scale, candidate)
        else:
            data = encode(candidate, fmt, settings.quality, settings, fast=True)
            attempt = _Attempt(data, None, scale, candidate)
            if len(data) <= target:
                return attempt
        if len(attempt.data) < len(best.data):
            best = attempt
        scale *= 0.85

    return best


# ---------------------------------------------------------------------------
# Быстрый путь: честный lossless
# ---------------------------------------------------------------------------

def _try_lossless_jpeg(
    raw: bytes,
    image: Image.Image,
    settings: Settings,
    target: int | None,
) -> tuple[bytes | None, str]:
    """Пробует уложиться в лимит, вообще не трогая пиксели.

    Возвращает байты и пустую причину при успехе, иначе None и объяснение,
    почему настоящий lossless тут неприменим. Молча подменять его пережатием
    нельзя: пользователь выбрал режим именно ради неизменных пикселей.
    """
    if not MOZJPEG_AVAILABLE:
        return None, "библиотека оптимизации JPEG недоступна"
    if (image.format or "").upper() not in {"JPEG", "MPO"}:
        return None, "исходник не JPEG — перекодирование неизбежно"
    if settings.exact_size_enabled and image.size != (settings.exact_width, settings.exact_height):
        return None, "кадр нужно привести к точному размеру"
    if settings.max_side_enabled and max(image.size) > settings.max_side:
        return None, "нужно уменьшить разрешение"
    icc = image.info.get("icc_profile")
    if settings.convert_to_srgb and icc and not _is_srgb(icc):
        return None, "цвета нужно пересчитать в sRGB"
    if not settings.keep_metadata and image.getexif().get(274, 1) not in (0, 1):
        # Ориентация зашита в EXIF: выбросив метаданные, мы положим фото набок.
        return None, "поворот записан в метаданных, которые просили удалить"

    optimized = _mozjpeg_pass(raw, settings)
    if target is not None and len(optimized) > target:
        return None, "без потерь в лимит не уложиться"
    return (optimized if len(optimized) <= len(raw) else raw), ""


# ---------------------------------------------------------------------------
# Основная точка входа
# ---------------------------------------------------------------------------

def compress_bytes(
    raw: bytes,
    settings: Settings,
    check_cancel=lambda: None,
) -> Encoded:
    """Сжимает картинку в памяти."""
    settings = settings.normalized()
    target = settings.target_bytes

    with Image.open(io.BytesIO(raw)) as opened:
        opened.load()
        source_format = opened.format
        fmt = resolve_output_format(settings, source_format)

        keeps_format = fmt == (source_format or "").lower() or (
            fmt == "jpeg" and (source_format or "").upper() in {"JPEG", "MPO"}
        )
        lossless_reason = ""
        if keeps_format and settings.mode in (MODE_SMART, MODE_LOSSLESS):
            lossless, lossless_reason = _try_lossless_jpeg(raw, opened, settings, target)
            if lossless is not None:
                return Encoded(
                    lossless, fmt, Status.LOSSLESS, opened.width, opened.height
                )
        elif settings.mode == MODE_LOSSLESS:
            lossless_reason = "формат вывода отличается от исходного"

        # Считаем до преобразований: потом исходные метаданные уже не спросить.
        transform = pixel_changing_step(opened, settings, fmt)
        image = prepare_image(opened, settings, fmt)

    original_size = image.size
    geometry_note = ""
    if settings.exact_size_enabled:
        image, geometry_note = apply_exact_size(image, settings, fmt)
    elif settings.max_side_enabled:
        image = fit_within(image, settings.max_side, settings)
    scale = image.width / original_size[0]

    if settings.mode == MODE_LOSSLESS:
        data = encode(image, fmt, 100, settings, lossless=True)
        # Обещать неизменные пиксели можно только если сама запись без потерь
        # (PNG и WebP-lossless) и по дороге кадр ничем не переписали. JPEG сюда
        # попадает лишь когда быстрый путь отказал, то есть пиксели изменятся.
        exact = fmt in {"png", "webp"} and keeps_format and not transform
        if target is not None and len(data) > target:
            # Не влезли — это важнее: такой файл площадка не примет.
            status = Status.TOO_BIG
            note = lossless_reason if not exact else ""
        elif exact:
            status, note = Status.LOSSLESS, ""
        else:
            status = Status.NOT_LOSSLESS
            note = transform or lossless_reason
        return Encoded(data, fmt, status, image.width, image.height, None, scale, note)

    if settings.mode == MODE_MANUAL or target is None:
        quality = settings.quality if fmt in LOSSY_FORMATS else None
        data = encode(image, fmt, settings.quality, settings)
        status = Status.OK if target is None or len(data) <= target else Status.TOO_BIG
        return Encoded(
            data, fmt, status, image.width, image.height, quality, scale, geometry_note
        )

    # Умный режим: сначала пытаемся сохранить разрешение, играя качеством.
    if fmt in LOSSY_FORMATS:
        attempt = _search_quality(image, fmt, settings, target, scale, check_cancel)
        if attempt is not None:
            return Encoded(
                finalize(attempt, fmt, settings), fmt, Status.OK,
                attempt.image.width, attempt.image.height, attempt.quality, scale,
                geometry_note,
            )
    else:
        data = encode(image, fmt, settings.quality, settings)
        if len(data) <= target:
            return Encoded(
                data, fmt, Status.OK, image.width, image.height, None, scale, geometry_note
            )

    if not settings.allow_downscale:
        lossy = fmt in LOSSY_FORMATS
        data = encode(image, fmt, settings.min_quality if lossy else settings.quality, settings)
        return Encoded(
            data, fmt, Status.TOO_BIG, image.width, image.height,
            settings.min_quality if lossy else None, scale,
            note=(
                "точный размер не даёт уменьшать — снизьте нижнюю планку качества"
                if settings.exact_size_enabled
                else "уменьшение картинки выключено"
            ),
        )

    best = _search_scale(image, fmt, settings, target, check_cancel)
    data = finalize(best, fmt, settings)
    fits = len(data) <= target
    note = ""
    if not fits and settings.min_side_enabled and min(best.image.size) <= settings.min_side:
        # Не сдались, а упёрлись в заданный минимум — это разные вещи.
        note = f"уперлись в минимум {settings.min_side} px"
    return Encoded(
        data, fmt, Status.OK if fits else Status.TOO_BIG,
        best.image.width, best.image.height, best.quality, scale * best.scale, note,
    )


def compress_file(
    source: Path,
    destination_for: "callable",
    settings: Settings,
    check_cancel=lambda: None,
) -> Result:
    """Читает файл, сжимает и кладёт результат туда, куда скажет callback.

    `destination_for(extension, size)` возвращает итоговый путь (или None,
    если файл нужно пропустить) — так вся логика имён и конфликтов живёт
    снаружи, а шаблону переименования доступен размер результата.
    """
    source_size = source.stat().st_size
    settings = settings.normalized()
    target = settings.target_bytes

    check_cancel()
    raw = source.read_bytes()

    # Файл уже подходит, ничего менять не просили — просто копируем.
    copy_extension = _copy_extension(raw, source, source_size, target, settings)
    if copy_extension is not None:
        width, height = _dimensions(raw)
        destination = destination_for(copy_extension, (width, height))
        if destination is None:
            return Result(Status.SKIPPED, source, None, source_size, source_size,
                          message="Файл с таким именем уже есть")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return Result(Status.COPIED, source, destination, source_size, source_size,
                      width, height, message="Уже подходит, скопирован без изменений")

    encoded = compress_bytes(raw, settings, check_cancel)
    data, fmt, status = encoded.data, encoded.fmt, encoded.status
    width, height = encoded.width, encoded.height

    destination = destination_for(output_extension(fmt), (width, height))
    if destination is None:
        return Result(Status.SKIPPED, source, None, source_size, len(data),
                      message="Файл с таким именем уже есть")

    # Пережатие вполне может дать файл тяжелее оригинала: PNG с шумом после
    # ресайза жмётся хуже, WebP lossless из lossy-источника раздувается втрое.
    # Отдать вместо него исходник можно только если тот равноценен: тот же
    # формат и те же пиксели. Иначе подмена сорвала бы заданный размер кадра.
    same_geometry = (width, height) == _dimensions(raw)
    if len(data) > source_size and fmt == _extension_format(source) and same_geometry:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        fits = target is None or source_size <= target
        return Result(
            Status.COPIED if fits else Status.TOO_BIG, source, destination,
            source_size, source_size, width, height,
            message="Оригинал оказался легче — оставлен как есть",
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)

    message = encoded.note
    if status is Status.LOSSLESS:
        message = "Без потери качества"
    elif status is Status.NOT_LOSSLESS:
        message = f"Точный lossless невозможен: {encoded.note}" if encoded.note else \
                  "Точный lossless невозможен, сохранено на максимуме качества"
    elif status is Status.TOO_BIG and not message:
        message = "Не влезает в лимит даже на минимальных настройках"
    return Result(status, source, destination, source_size, len(data),
                  width, height, encoded.quality, encoded.scale, message)


def format_from_suffix(suffix: str) -> str:
    """Формат по расширению файла — для случаев, когда открывать его незачем."""
    suffix = suffix.lower()
    if suffix in (".jpg", ".jpeg", ".jpe", ".jfif"):
        return "jpeg"
    if suffix in (".heic", ".heif", ".hif"):
        return "heif"
    if suffix in (".tif", ".tiff"):
        return "tiff"
    return suffix.lstrip(".")


def _copy_extension(
    raw: bytes, source: Path, source_size: int, target: int | None, settings: Settings
) -> str | None:
    """Расширение для копии файла либо None, если копировать нельзя.

    Копия допустима, только если результат совпал бы с пережатым по всем
    заявленным требованиям: вес, разрешение, формат и метаданные. Файл при
    этом обязан быть читаемой картинкой — иначе пустышка или переименованный
    текст уехали бы в выгрузку под видом готового снимка.
    """
    if target is None or source_size > target or not settings.copy_when_already_small:
        return None

    try:
        with Image.open(io.BytesIO(raw)) as image:
            actual = (image.format or "").lower()
            if resolve_output_format(settings, actual) != actual:
                return None
            if settings.exact_size_enabled and image.size != (
                settings.exact_width, settings.exact_height
            ):
                return None
            if settings.max_side_enabled and max(image.size) > settings.max_side:
                return None
            info = image.info
            has_metadata = bool(
                info.get("exif") or info.get("icc_profile") or info.get("comment")
            )
    except Exception:
        # Не открылось — пусть обычный путь честно вернёт ошибку.
        return None

    if not settings.keep_metadata and has_metadata:
        # Просили выкинуть метаданные — копией это не сделаешь.
        return None

    # У JPEG внутри может лежать что угодно: расширение подгоняем под
    # настоящий формат, иначе площадка получит PNG с именем .jpg.
    suffix = source.suffix.lower()
    return suffix if format_from_suffix(suffix) == actual else output_extension(actual)


def _extension_format(path: Path) -> str:
    """Формат самого файла на диске — без учёта выбранного формата вывода."""
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg", ".jpe", ".jfif"):
        return "jpeg"
    return suffix.lstrip(".")


def _dimensions(raw: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image = ImageOps.exif_transpose(image) or image
            return image.size
    except Exception:
        return (0, 0)
