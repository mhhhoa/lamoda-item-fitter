"""Получение альфа-маски объекта.

В этом пайплайне к маске предъявляются необычно мягкие требования. В обычном
«вырезании фона» маска отвечает за качество кромки, и любая её ошибка сразу видна
ореолом. Здесь кромку чинит compose.compose по уравнению композитинга, а маска нужна
лишь для того, чтобы (а) знать, где НЕ фон при фите модели фона, и (б) знать, куда
не применять деление. Поэтому лёгкой модели достаточно, и тяжёлый torch не нужен.

Бэкенды:
    simple  — классический, без нейросетей и без интернета. Работает от того, что
              студийный фон гладкий: считает отклонение от модели фона. Для чистой
              съёмки на циклораме этого часто хватает.
    rembg   — нейросетевой (onnxruntime). Нужен для лайфстайл-кадров с реквизитом,
              где «не фон» нельзя определить по одной лишь гладкости.
"""

from __future__ import annotations

from typing import Callable, Protocol

import numpy as np
from scipy import ndimage

from .background import BackgroundModel

__all__ = ["get_backend", "available_backends", "refine_alpha_from_background"]


class MattingBackend(Protocol):
    def __call__(self, srgb: np.ndarray) -> np.ndarray:
        """(H, W, 3) sRGB [0,1] -> (H, W) alpha [0,1]."""


# --- классический бэкенд ----------------------------------------------------


def _simple_matte(srgb: np.ndarray, border: int = 24, sensitivity: float = 0.055) -> np.ndarray:
    """Маска по отклонению от цвета фона, взятого с рамки кадра.

    Работает на том, что у каталожного кадра рамка почти всегда чистый фон,
    а фон гладкий. Не умеет отличать реквизит от фона — для лайфстайла нужен rembg.
    """
    h, w, _ = srgb.shape
    b = max(4, min(border, h // 8, w // 8))
    frame = np.concatenate(
        [
            srgb[:b].reshape(-1, 3),
            srgb[-b:].reshape(-1, 3),
            srgb[:, :b].reshape(-1, 3),
            srgb[:, -b:].reshape(-1, 3),
        ]
    )
    ref = np.median(frame, axis=0)

    dist = np.linalg.norm(srgb - ref, axis=-1)
    # Порог адаптивный: подстраивается под шум конкретного кадра, но не опускается
    # ниже sensitivity, иначе на чистом фоне маска рассыпется на зерно.
    noise = float(np.median(np.abs(dist - np.median(dist)))) * 1.4826
    thr = max(sensitivity, 4.0 * noise)

    solid = dist > thr
    solid = ndimage.binary_closing(solid, np.ones((5, 5), bool))
    solid = ndimage.binary_opening(solid, np.ones((3, 3), bool))

    # Оставляем только крупные компоненты: мелочь — это шум и пылинки на фоне.
    labels, n = ndimage.label(solid)
    if n:
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        keep = np.flatnonzero(sizes > max(500, 0.0015 * h * w))
        solid = np.isin(labels, keep) if keep.size else solid

    solid = ndimage.binary_fill_holes(solid)
    # Отражение под товаром НЕ должно попасть в маску объекта: оно обязано остаться
    # в зоне деления, иначе не убелится и не станет серой тенью.
    soft = np.clip(dist / max(thr * 2.0, 1e-6), 0.0, 1.0)
    return np.maximum(solid.astype(np.float32), soft * solid).astype(np.float32)


# --- нейросетевой бэкенд ----------------------------------------------------

_REMBG_SESSIONS: dict[str, object] = {}


def _rembg_matte_factory(model_name: str) -> Callable[[np.ndarray], np.ndarray]:
    def run(srgb: np.ndarray) -> np.ndarray:
        from PIL import Image
        from rembg import new_session, remove

        if model_name not in _REMBG_SESSIONS:
            import onnxruntime as ort

            avail = ort.get_available_providers()
            providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in avail]
            _REMBG_SESSIONS[model_name] = new_session(model_name, providers=providers)

        img = Image.fromarray(np.round(np.clip(srgb, 0, 1) * 255).astype(np.uint8), "RGB")
        mask = remove(img, session=_REMBG_SESSIONS[model_name], only_mask=True, post_process_mask=True)
        return (np.asarray(mask, dtype=np.float32) / 255.0).astype(np.float32)

    return run


_BACKENDS: dict[str, Callable[[], MattingBackend]] = {
    "simple": lambda: _simple_matte,
    "rembg": lambda: _rembg_matte_factory("isnet-general-use"),
    "rembg-birefnet": lambda: _rembg_matte_factory("birefnet-general"),
    "rembg-u2net": lambda: _rembg_matte_factory("u2net"),
}


def available_backends() -> list[str]:
    return list(_BACKENDS)


def get_backend(name: str) -> MattingBackend:
    """Возвращает функцию матирования по имени. Падает с понятным текстом, если нет зависимостей."""
    if name not in _BACKENDS:
        raise ValueError(f"Неизвестный бэкенд матирования {name!r}. Доступны: {', '.join(_BACKENDS)}")
    if name.startswith("rembg"):
        try:
            import rembg  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Бэкенд 'rembg' требует установки: pip install 'rembg[cpu]'.\n"
                "Либо используйте --matting simple — он не требует нейросетей."
            ) from exc
    return _BACKENDS[name]()


# --- уточнение альфы по модели фона -----------------------------------------


def refine_alpha_from_background(
    img_lin: np.ndarray,
    alpha: np.ndarray,
    model: BackgroundModel,
    band_low: float = 0.02,
    band_high: float = 0.98,
    min_contrast: float = 0.06,
) -> np.ndarray:
    """Пересчитывает альфу на кромке аналитически, по уравнению композитинга.

    Нейросеть отдаёт маску, посчитанную на уменьшенной копии кадра, поэтому её
    кромка размыта на несколько пикселей. Но у нас уже есть модель фона B, а значит
    из I = a*F + (1-a)*B альфу можно достать точно:

        a = <I - B, F - B> / |F - B|^2

    где F берётся от ближайшего уверенно-объектного пикселя. Это даёт кромку
    пиксельной точности на шнурках, каблуках и строчке, где размытая маска мажет.

    Если товар по цвету почти совпал с фоном (белая сандалия на светлом фоне),
    знаменатель вырождается и уточнению верить нельзя — там остаётся исходная альфа.
    """
    band = (alpha > band_low) & (alpha < band_high)
    if not band.any():
        return alpha

    solid = alpha >= band_high
    if not solid.any():
        return alpha

    # Цвет товара рядом с кромкой — от ближайшего уверенно-объектного пикселя.
    idx = ndimage.distance_transform_edt(~solid, return_distances=False, return_indices=True)
    fg = img_lin[idx[0], idx[1]]

    diff_fb = fg - model.surface
    denom = np.sum(diff_fb * diff_fb, axis=-1)
    numer = np.sum((img_lin - model.surface) * diff_fb, axis=-1)

    reliable = band & (denom > min_contrast**2)
    if not reliable.any():
        return alpha

    refined = alpha.copy()
    refined[reliable] = np.clip(numer[reliable] / denom[reliable], 0.0, 1.0)
    return refined.astype(np.float32)
