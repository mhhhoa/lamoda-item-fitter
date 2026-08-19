"""Подгонка кадра под правила маркетплейса.

Инвариант, ради которого всё написано: низ товара стоит ровно на нижней линии
отступа, товар отцентрован по горизонтали и не выходит за поля.

Ключ к точности — порядок действий. Товар сначала масштабируется, потом его
габарит измеряется уже в отмасштабированном куске, и только потом кусок
кладётся на холст целочисленным сдвигом. Считать координаты заранее нельзя:
Ланцош размывает край на пару пикселей, и арифметически «точная» позиция
промахивается мимо линии.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image
from scipy import ndimage

from . import angle as angle_mod
from .background import (
    difference_map, estimate_background, feather_alpha, flatten_background, new_canvas,
)
from .config import Preset
from .mask import Box, build_masks, refine_bbox

FITTED = "fitted"
PASSTHROUGH = "passthrough"
SKIPPED = "skipped"

CROP_PAD = 4  # запас исходника вокруг расчётного куска, px


@dataclass
class FitMetrics:
    source_size: tuple[int, int] = (0, 0)
    item_box: Box | None = None
    scale: float = 0.0
    background: tuple[int, int, int] = (255, 255, 255)
    threshold: int = 0
    shadow_px: int = 0
    #: фактические отступы готового холста
    margins: dict[str, int] = field(default_factory=dict)
    angle_kind: str = angle_mod.OTHER
    angle_label: str = ""
    angle_confidence: float = 0.0


@dataclass
class FitResult:
    status: str
    image: Image.Image | None = None
    metrics: FitMetrics = field(default_factory=FitMetrics)
    warnings: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (FITTED, PASSTHROUGH)


def _analysis_copy(image: Image.Image, max_side: int) -> tuple[np.ndarray, float]:
    """Уменьшенная копия для анализа и её масштаб относительно оригинала."""
    if max(image.size) <= max_side:
        return np.asarray(image), 1.0
    small = image.copy()
    small.thumbnail((max_side, max_side), Image.LANCZOS)
    return np.asarray(small), small.width / image.width


def _measure(array: np.ndarray, background: np.ndarray, threshold: int,
             preset: Preset) -> tuple[np.ndarray, Box | None]:
    """Маска и габарит товара на готовом изображении."""
    from .mask import _bbox_of, _clean  # локальный импорт: внутренняя кухня маски

    mask, _ = _clean(difference_map(array, background) >= threshold, preset.mask)
    return mask, _bbox_of(mask)


def _scaled_piece(
    image: Image.Image, box: Box, scale: float, preset: Preset
) -> Image.Image:
    """Отмасштабированный кусок исходника, которого хватает на весь холст.

    Берём ровно столько, сколько нужно вокруг товара: слева и справа — половина
    свободного места, сверху — до верхнего края холста, снизу — на нижний
    отступ. Масштабировать кадр целиком нельзя: при мелком товаре в большом
    кадре это гигабайты впустую.
    """
    box_w = box[2] - box[0] + 1
    box_h = box[3] - box[1] + 1
    side = (preset.canvas.width / scale - box_w) / 2.0
    above = (preset.baseline_y - box_h * scale) / scale
    below = (preset.canvas.height - preset.baseline_y) / scale

    x0 = max(0, math.floor(box[0] - side) - CROP_PAD)
    y0 = max(0, math.floor(box[1] - above) - CROP_PAD)
    x1 = min(image.width, math.ceil(box[2] + 1 + side) + CROP_PAD)
    y1 = min(image.height, math.ceil(box[3] + 1 + below) + CROP_PAD)
    piece = image.crop((x0, y0, x1, y1))
    size = (max(1, round(piece.width * scale)), max(1, round(piece.height * scale)))
    return piece.resize(size, Image.LANCZOS, reducing_gap=3.0)


def _place(
    piece: Image.Image, item: Box, preset: Preset, background: np.ndarray
) -> tuple[Image.Image, Box]:
    """Кладёт кусок на холст так, чтобы товар встал ровно по правилам."""
    item_w = item[2] - item[0] + 1
    item_h = item[3] - item[1] + 1
    target_x0 = int(round(preset.center_x - item_w / 2.0))
    target_y1 = preset.baseline_y - 1
    offset = (target_x0 - item[0], target_y1 - item[3])

    canvas = new_canvas(preset.canvas.width, preset.canvas.height, background)

    # растушёвываем только те края вставки, что лежат внутри холста и далеко
    # от товара: иначе на градиентном фоне остаётся заметный стык
    feather = preset.background.feather
    sides = {
        "left": offset[0] > 0 and item[0] > feather,
        "right": offset[0] + piece.width < preset.canvas.width
                 and piece.width - 1 - item[2] > feather,
        "top": offset[1] > 0 and item[1] > feather,
        "bottom": offset[1] + piece.height < preset.canvas.height
                  and piece.height - 1 - item[3] > feather,
    }
    if any(sides.values()):
        alpha = feather_alpha(piece.width, piece.height, feather, sides)
        canvas.paste(piece, offset, Image.fromarray((alpha * 255).astype(np.uint8), mode="L"))
    else:
        canvas.paste(piece, offset)

    placed = (target_x0, target_y1 - item_h + 1, target_x0 + item_w - 1, target_y1)
    return canvas, placed


def fit_image(image: Image.Image, preset: Preset) -> FitResult:
    """Приводит кадр к правилам маркетплейса."""
    warnings: list[str] = []
    metrics = FitMetrics(source_size=image.size)

    analysis, analysis_scale = _analysis_copy(image, preset.analysis_max_side)
    background = estimate_background(analysis, preset.background.border_fraction)
    metrics.background = tuple(int(c) for c in background)
    if int(background.min()) < preset.background.min_level:
        warnings.append(f"фон темнее допустимого {metrics.background}, проверьте съёмку")

    masks = build_masks(analysis, background, preset.mask, preset.background.border_fraction)
    metrics.threshold = masks.threshold
    metrics.shadow_px = masks.shadow_px
    if not masks.found:
        return FitResult(SKIPPED, metrics=metrics, warnings=warnings,
                         reason="товар на кадре не найден — фон слишком тёмный или кадр пустой")

    angle = angle_mod.classify(masks.solid, masks.bbox, masks.components)
    metrics.angle_kind, metrics.angle_label = angle.kind, angle.label
    metrics.angle_confidence = angle.confidence

    cropped = masks.cropped_sides
    if cropped:
        names = {"left": "слева", "right": "справа", "top": "сверху"}
        sides = ", ".join(names[s] for s in cropped)
        canvas_size = (preset.canvas.width, preset.canvas.height)
        if preset.cropped_policy == "passthrough":
            if image.size == canvas_size:
                return FitResult(
                    PASSTHROUGH, image=image, metrics=metrics, warnings=warnings,
                    reason=f"макро-кадр (товар выходит за край {sides}), перенесён без подгонки")
            return FitResult(
                SKIPPED, metrics=metrics, warnings=warnings,
                reason=f"макро-кадр (товар выходит за край {sides}), а размер не "
                       f"{canvas_size[0]}×{canvas_size[1]} — обработайте вручную")
        if preset.cropped_policy == "skip":
            return FitResult(SKIPPED, metrics=metrics, warnings=warnings,
                             reason=f"товар выходит за край {sides} — авто-подгонка невозможна")
        warnings.append(f"товар выходит за край {sides}, габарит определён по видимой части")

    if masks.touches.get("bottom"):
        warnings.append("низ товара обрезан краем исходника")
    if masks.uncertainty > preset.mask.uncertainty_warn:
        warnings.append("границы товара нечёткие — проверьте результат")
    shadow_excluded = masks.shadow_confirmed and preset.shadow_mode == "exclude"
    if shadow_excluded and masks.bbox is not None:
        # мягкий край подошвы в несколько пикселей — норма, о нём молчим;
        # эталоны Ламоды выровнены как раз по плотной кромке
        item_height = masks.bbox[3] - masks.bbox[1] + 1
        if masks.confirmed_shadow_px >= preset.mask.shadow_notice_ratio * item_height:
            warnings.append(
                f"под товаром мягкая тень ({masks.confirmed_shadow_px} px), в габарит не включена")

    # габарит: с уменьшенной копии на оригинал и уточнение по оригиналу
    box = masks.item_bbox(preset.shadow_mode)
    if analysis_scale < 1.0:
        approx = tuple(int(round(v / analysis_scale)) for v in box)
        pad = int(math.ceil(2 / analysis_scale)) + 2
        full = np.asarray(image)  # у крупных исходников это десятки мегабайт
        box = refine_bbox(full, background, masks.threshold, approx, pad)
        if shadow_excluded:
            # уточнять низ обычным порогом нельзя — он вернёт тень обратно
            core = refine_bbox(full, background, preset.mask.core_threshold, approx, pad)
            box = (box[0], box[1], box[2], min(box[3], core[3]))
    metrics.item_box = box

    box_w, box_h = box[2] - box[0] + 1, box[3] - box[1] + 1
    scale = min(preset.zone_width / box_w, preset.zone_height / box_h) * preset.fill
    if scale > 1.01:
        warnings.append(f"исходник мельче нужного, увеличен в {scale:.2f}× — возможна потеря резкости")

    canvas: Image.Image | None = None
    placed: Box | None = None
    for _ in range(3):
        piece = _scaled_piece(image, box, scale, preset)
        piece_array = np.asarray(piece)
        _, visible = _measure(piece_array, background, masks.threshold, preset)
        if visible is None:
            break
        item = visible
        if shadow_excluded:
            # низ выравниваем по плотной кромке подошвы: именно так выровнены
            # эталоны Ламоды, а мягкий край на пару пикселей уходит в отступ
            _, core = _measure(piece_array, background, preset.mask.core_threshold, preset)
            if core is not None:
                item = (visible[0], visible[1], visible[2], min(visible[3], core[3]))
        item_w = visible[2] - visible[0] + 1
        item_h = item[3] - visible[1] + 1
        if item_w > preset.zone_width or item_h > preset.zone_height:
            # размытие края после ресайза добавляет пару пикселей — ужимаем
            scale *= min(preset.zone_width / item_w, preset.zone_height / item_h)
            continue
        canvas, placed = _place(piece, item, preset, background)
        break
    metrics.scale = scale

    if canvas is None or placed is None:
        return FitResult(SKIPPED, metrics=metrics, warnings=warnings,
                         reason="не удалось разместить товар на холсте")

    # отступы берём из размещения, а не из повторного замера: положение товара
    # известно точно, и цифры в отчёте обязаны совпадать с тем, что сделано
    metrics.margins = {
        "top": int(placed[1]),
        "bottom": int(preset.canvas.height - 1 - placed[3]),
        "left": int(placed[0]),
        "right": int(preset.canvas.width - 1 - placed[2]),
    }

    array = np.asarray(canvas).copy()
    item_mask, _ = _measure(array, background, masks.threshold, preset)
    protect = ndimage.binary_dilation(
        item_mask, structure=np.ones((3, 3)),
        iterations=max(1, preset.background.protect_dilate_px),
    )
    flatten_background(array, background, difference_map(array, background),
                       protect, preset.background)

    return FitResult(FITTED, image=Image.fromarray(array), metrics=metrics, warnings=warnings)
