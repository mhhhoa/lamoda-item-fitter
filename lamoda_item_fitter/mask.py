"""Выделение товара на светлом фоне и замер его габарита."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from .background import difference_map
from .config import MaskCfg

Box = tuple[int, int, int, int]  # x0, y0, x1, y1 — включительно


@dataclass
class MaskResult:
    """Что удалось узнать о товаре на кадре."""

    solid: np.ndarray
    soft: np.ndarray
    bbox: Box | None
    soft_bbox: Box | None
    threshold: int
    soft_threshold: int
    components: int
    #: габарит по заведомо контрастной части товара
    core_bbox: Box | None = None
    #: под товаром опознана именно тень, а не светлая деталь
    shadow_confirmed: bool = False
    #: край кадра, которого касается товар
    touches: dict[str, bool] = field(default_factory=dict)
    #: насколько мягкий материал (тень, полупрозрачность) свисает ниже подошвы
    shadow_px: int = 0
    #: высота подтверждённой тени между подошвой и низом плотной маски
    confirmed_shadow_px: int = 0
    #: расхождение габарита между плотной и мягкой масками, доля размера товара
    uncertainty: float = 0.0

    @property
    def found(self) -> bool:
        return self.bbox is not None

    def item_bbox(self, shadow_mode: str) -> Box | None:
        """Габарит товара с учётом выбранного режима тени."""
        if self.bbox is None:
            return None
        if shadow_mode == "exclude" and self.shadow_confirmed and self.core_bbox is not None:
            x0, y0, x1, y1 = self.bbox
            return x0, y0, x1, min(y1, self.core_bbox[3])
        return self.bbox

    @property
    def cropped_sides(self) -> list[str]:
        """Края, обрезка по которым делает габарит недостоверным.

        Низ не считается: товар и так совмещается с нижней линией, поэтому
        плотно скадрированный снизу исходник подгоняется штатно.
        """
        return [side for side in ("left", "right", "top") if self.touches.get(side)]


def background_variation(difference: np.ndarray, border_fraction: float) -> float:
    """Насколько «шумит» сам фон — по рамке кадра.

    Берётся максимум из двух оценок. Медиана с MAD устойчива, даже когда товар
    занимает половину рамки (макро-кадры), но схлопывается в ноль на дискретном
    шуме, где больше половины значений совпадают; 95-й перцентиль такой шум
    видит и терпит до 5% посторонних пикселей в рамке.
    """
    height, width = difference.shape[:2]
    band = max(2, int(round(min(height, width) * border_fraction)))
    band = min(band, height // 2, width // 2)
    border = np.concatenate([
        difference[:band].ravel(), difference[-band:].ravel(),
        difference[:, :band].ravel(), difference[:, -band:].ravel(),
    ]).astype(np.float64)
    center = float(np.median(border))
    sigma = 1.4826 * float(np.median(np.abs(border - center)))
    return max(center + 6.0 * sigma, float(np.percentile(border, 95.0)))


def _looks_like_shadow(
    difference: np.ndarray, mask: np.ndarray, top: int, bottom: int, max_contrast: int
) -> bool:
    """Отличает мягкую тень под товаром от светлой детали самого товара.

    Тень — это подсвеченный фон: она слабая и гаснет по мере удаления от
    подошвы. Светлая подошва такой же слабой может быть, но по высоте она
    ровная. Поэтому решает не яркость, а наличие затухания сверху вниз.
    """
    if bottom - top < 4:
        return False
    band = difference[top:bottom + 1]
    band_mask = mask[top:bottom + 1]
    if not band_mask.any():
        return False
    counts = band_mask.sum(axis=1)
    rows = np.flatnonzero(counts > 0)
    if rows.size < 4:
        return False
    profile = np.array([
        band[i][band_mask[i]].mean() for i in rows
    ], dtype=np.float64)
    if profile.max() > max_contrast:
        return False
    head, tail = profile[0], profile[-1]
    if head <= 0:
        return False
    decaying = np.mean(np.diff(profile) <= 0.5) >= 0.7
    return bool(tail <= 0.6 * head and decaying)


def _bbox_of(mask: np.ndarray) -> Box | None:
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]), int(rows[-1])


def _close(mask: np.ndarray, size: int) -> np.ndarray:
    """Смыкание с защитой краёв.

    Без подкладки scipy считает всё за кадром фоном и съедает по краю столько
    же пикселей, сколько велико ядро, — товар, лежащий на краю, переставал бы
    определяться как обрезанный.
    """
    if size < 2:
        return mask
    padded = np.pad(mask, size, mode="edge")
    closed = ndimage.binary_closing(padded, structure=np.ones((size, size)))
    return closed[size:-size, size:-size]


def _clean(mask: np.ndarray, cfg: MaskCfg) -> tuple[np.ndarray, int]:
    """Смыкает разрывы, заливает дыры и выбрасывает мелкий мусор."""
    mask = ndimage.binary_fill_holes(_close(mask, cfg.close_px))
    labels, count = ndimage.label(mask)
    if count == 0:
        return mask, 0
    areas = np.bincount(labels.ravel())
    areas[0] = 0
    keep = areas >= max(1.0, areas.max() * cfg.min_component_fraction)
    keep[0] = False
    return keep[labels], int(keep.sum())


def _edge_touches(mask: np.ndarray, pad: int) -> dict[str, bool]:
    pad = max(1, pad)
    return {
        "left": bool(mask[:, :pad].any()),
        "right": bool(mask[:, -pad:].any()),
        "top": bool(mask[:pad].any()),
        "bottom": bool(mask[-pad:].any()),
    }


def build_masks(
    array: np.ndarray, background: np.ndarray, cfg: MaskCfg, border_fraction: float = 0.02
) -> MaskResult:
    """Строит маску товара по рабочей копии кадра.

    Порог берётся от шума фона, а не от гистограммы: товар — это всё, что
    отличается от фона сильнее, чем фон отличается сам от себя. На идеально
    ровном фоне эталонов это даёт нижнюю границу коридора и позволяет поймать
    светлую подошву, которую фиксированный высокий порог срезал бы.
    """
    difference = difference_map(array, background)
    noise = background_variation(difference, border_fraction)
    threshold = int(np.clip(round(noise) + 3, cfg.solid_threshold_min, cfg.solid_threshold_max))
    # мягкая маска должна оставаться выше собственной изменчивости фона,
    # иначе на шумном исходнике она поймает весь кадр и наврёт про тень
    soft_threshold = int(np.clip(max(cfg.soft_threshold, round(noise) + 1), 1, threshold - 1))

    solid, components = _clean(difference >= threshold, cfg)
    bbox = _bbox_of(solid)

    # заведомо контрастная часть товара — опора для распознавания тени
    core_bbox = None
    shadow_confirmed = False
    confirmed_shadow_px = 0
    if bbox is not None and cfg.core_threshold > threshold:
        core, _ = _clean(difference >= cfg.core_threshold, cfg)
        core_bbox = _bbox_of(core)
        if core_bbox is not None and bbox[3] > core_bbox[3]:
            shadow_confirmed = _looks_like_shadow(
                difference, solid, core_bbox[3] + 1, bbox[3], cfg.shadow_max_contrast
            )
            if shadow_confirmed:
                confirmed_shadow_px = bbox[3] - core_bbox[3]

    soft_raw = _close(difference >= soft_threshold, cfg.close_px)
    if bbox is not None and soft_raw.any():
        # мягкую маску оставляем только там, где она примыкает к товару:
        # тень остаётся, дальний мусор и виньетка — нет
        soft_labels, soft_count = ndimage.label(soft_raw)
        touching = np.unique(soft_labels[solid])
        touching = touching[touching > 0]
        soft = np.isin(soft_labels, touching) if soft_count else soft_raw
    else:
        soft = soft_raw
    soft_bbox = _bbox_of(soft)

    shadow_px = 0
    uncertainty = 0.0
    if bbox is not None and soft_bbox is not None:
        shadow_px = max(0, soft_bbox[3] - bbox[3])
        size = max(bbox[2] - bbox[0] + 1, bbox[3] - bbox[1] + 1)
        spread = max(abs(soft_bbox[0] - bbox[0]), abs(soft_bbox[2] - bbox[2]),
                     abs(soft_bbox[1] - bbox[1]), shadow_px)
        uncertainty = spread / size if size else 0.0

    return MaskResult(
        solid=solid, soft=soft, bbox=bbox, soft_bbox=soft_bbox, threshold=threshold,
        soft_threshold=soft_threshold, components=components, core_bbox=core_bbox,
        shadow_confirmed=shadow_confirmed, confirmed_shadow_px=confirmed_shadow_px,
        touches=_edge_touches(solid, cfg.edge_touch_px),
        shadow_px=shadow_px, uncertainty=uncertainty,
    )


def refine_bbox(
    array: np.ndarray, background: np.ndarray, threshold: int, approx: Box, pad: int
) -> Box:
    """Уточняет габарит по кадру в полном разрешении.

    Маска и классификация считаются на уменьшенной копии — это быстро, но даёт
    погрешность в несколько пикселей. Геометрия у нас точная, поэтому границы
    пересчитываются по оригиналу в окрестности найденного габарита.
    """
    height, width = array.shape[:2]
    x0 = max(0, approx[0] - pad)
    y0 = max(0, approx[1] - pad)
    x1 = min(width - 1, approx[2] + pad)
    y1 = min(height - 1, approx[3] + pad)
    region = array[y0:y1 + 1, x0:x1 + 1]
    mask = difference_map(region, background) >= threshold
    mask = ndimage.binary_opening(mask, structure=np.ones((3, 3)))
    box = _bbox_of(mask)
    if box is None:
        return approx
    return box[0] + x0, box[1] + y0, box[2] + x0, box[3] + y0
