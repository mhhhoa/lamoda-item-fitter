"""Финальные операции: целевой оттенок фона, геометрия под спецификацию."""

from __future__ import annotations

import numpy as np
from PIL import Image

from .colorspace import hex_to_rgb

__all__ = ["apply_target_background", "fit_geometry"]


def apply_target_background(
    srgb: np.ndarray, alpha: np.ndarray, target_hex: str = "#FFFFFF"
) -> np.ndarray:
    """Подкрашивает фон в целевой оттенок, если он не чисто белый.

    Часть категорий на маркетплейсах принимает не 255,255,255, а светло-серый
    (например #EFEFEF). После нормализации фон равен единице, поэтому достаточно
    домножить его на целевое значение, не трогая товар.
    """
    target = np.asarray(hex_to_rgb(target_hex), dtype=np.float32) / 255.0
    if np.allclose(target, 1.0):
        return srgb

    bg_weight = (1.0 - np.clip(alpha, 0.0, 1.0))[..., None]
    scale = 1.0 - (1.0 - target)[None, None, :] * bg_weight
    return np.clip(srgb * scale, 0.0, 1.0).astype(np.float32)


def fit_geometry(
    srgb: np.ndarray,
    mode: str = "keep",
    width: int = 1500,
    height: int = 2000,
    pad_hex: str = "#FFFFFF",
) -> np.ndarray:
    """Приводит кадр к целевому размеру.

    keep  — не трогать (основной режим: кадры из генерации уже нужного размера).
    fit   — вписать целиком и добить полями цвета фона. Товар никогда не обрезается.
    cover — заполнить кадр и обрезать лишнее по длинной стороне.
    """
    if mode == "keep":
        return srgb
    if mode not in ("fit", "cover"):
        raise ValueError(f"Неизвестный режим геометрии {mode!r}. Допустимо: keep, fit, cover")

    h, w, _ = srgb.shape
    scale = min(width / w, height / h) if mode == "fit" else max(width / w, height / h)
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))

    img = Image.fromarray(np.round(np.clip(srgb, 0, 1) * 255).astype(np.uint8), "RGB")
    img = img.resize((new_w, new_h), Image.LANCZOS)
    arr = np.asarray(img, dtype=np.float32) / 255.0

    if mode == "cover":
        top, left = (new_h - height) // 2, (new_w - width) // 2
        return arr[top : top + height, left : left + width]

    pad = np.asarray(hex_to_rgb(pad_hex), dtype=np.float32) / 255.0
    canvas = np.broadcast_to(pad, (height, width, 3)).copy()
    top, left = (height - new_h) // 2, (width - new_w) // 2
    canvas[top : top + new_h, left : left + new_w] = arr
    return canvas
