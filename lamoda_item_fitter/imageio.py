"""Чтение и запись изображений."""

from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image, ImageOps

from .config import OutputCfg

SUPPORTED_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".jpe", ".png", ".webp", ".tif", ".tiff", ".bmp"}
)

#: белый, на который сводится альфа-канал до того, как оценён фон кадра
ALPHA_MATTE = (255, 255, 255)


def is_supported(path: Path | str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES


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


def load_image(path: Path | str) -> Image.Image:
    """Загружает кадр: разворот по EXIF, sRGB, RGB без альфы."""
    image = Image.open(path)
    image.load()
    image = ImageOps.exif_transpose(image)
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
    return _to_srgb(image)


def _encode(image: Image.Image, fmt: str, quality: int, cfg: OutputCfg) -> bytes:
    buffer = io.BytesIO()
    if fmt == "png":
        image.save(buffer, "PNG", optimize=cfg.png_optimize)
    else:
        image.save(
            buffer, "JPEG", quality=quality,
            subsampling=cfg.jpeg_subsampling, optimize=True, progressive=False,
        )
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
