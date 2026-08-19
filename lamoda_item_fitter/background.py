"""Работа с фоном: оценка цвета, выравнивание, заливка холста."""

from __future__ import annotations

import numpy as np
from PIL import Image

from .config import BackgroundCfg


def estimate_background(array: np.ndarray, border_fraction: float = 0.02) -> np.ndarray:
    """Цвет фона — медиана по рамке вдоль краёв кадра.

    Медиана, а не среднее: если товар подходит вплотную к краю, он не утянет
    оценку за собой.
    """
    height, width = array.shape[:2]
    band = max(2, int(round(min(height, width) * border_fraction)))
    band = min(band, height // 2, width // 2)
    frame = np.concatenate([
        array[:band].reshape(-1, 3),
        array[-band:].reshape(-1, 3),
        array[:, :band].reshape(-1, 3),
        array[:, -band:].reshape(-1, 3),
    ])
    return np.median(frame, axis=0).astype(np.int16)


def difference_map(array: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Насколько каждый пиксель отличается от фона — максимум по каналам."""
    diff = np.abs(array.astype(np.int16) - background.reshape(1, 1, 3))
    return diff.max(axis=2).astype(np.int16)


def flatten_background(
    array: np.ndarray,
    background: np.ndarray,
    difference: np.ndarray,
    protect: np.ndarray | None,
    cfg: BackgroundCfg,
) -> np.ndarray:
    """Мягкое выравнивание: почти-фоновые пиксели вне товара становятся фоном.

    Убирает шум матрицы и любой остаточный стык на границе вставки. Маска
    товара (расширенная) защищена, поэтому светлые детали внутри силуэта
    не пострадают.
    """
    if cfg.flatten_threshold <= 0:
        return array
    target = difference < cfg.flatten_threshold
    if protect is not None:
        target &= ~protect
    if target.any():
        array[target] = background.astype(array.dtype)
    return array


def new_canvas(width: int, height: int, background: np.ndarray) -> Image.Image:
    return Image.new("RGB", (width, height), tuple(int(c) for c in background))


def feather_alpha(width: int, height: int, feather: int, sides: dict[str, bool]) -> np.ndarray:
    """Альфа для вставки: линейный спад к тем краям, которые разрешено растушевать."""
    alpha = np.ones((height, width), dtype=np.float32)
    if feather <= 0:
        return alpha
    ramp_len = min(feather, width // 2, height // 2)
    if ramp_len <= 0:
        return alpha
    ramp = np.linspace(0.0, 1.0, ramp_len + 2, dtype=np.float32)[1:-1]
    if sides.get("left"):
        alpha[:, :ramp_len] = np.minimum(alpha[:, :ramp_len], ramp[None, :])
    if sides.get("right"):
        alpha[:, -ramp_len:] = np.minimum(alpha[:, -ramp_len:], ramp[::-1][None, :])
    if sides.get("top"):
        alpha[:ramp_len] = np.minimum(alpha[:ramp_len], ramp[:, None])
    if sides.get("bottom"):
        alpha[-ramp_len:] = np.minimum(alpha[-ramp_len:], ramp[::-1][:, None])
    return alpha
