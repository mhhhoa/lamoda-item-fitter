"""Сборка кадра: чистка кромки и композитинг объекта на нормализованный фон.

Здесь живёт то, что в плане названо декомпрессией цвета на кромке. Вокруг обуви
пиксели кромки — это физическая смесь товара и фона: на бежевой циклораме белая
кожа сандалии по краю кремовая, на зелёной — кожа ног по контуру зеленит.
Если просто подложить белый фон, эта кайма останется и будет читаться как грязный
контур. Поэтому смесь разбирается обратно по уравнению композитинга.

Важно, что на объект flat-field деление НЕ применяется: разделив товар на модель
фона, мы бы его пересветили и перекрасили, а цвет товара на карточке маркетплейса
менять нельзя.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from .background import BackgroundModel

__all__ = ["background_ratio_field", "compose", "protect_mask"]


def background_ratio_field(
    img_lin: np.ndarray,
    model: BackgroundModel,
    alpha: np.ndarray,
    bg_threshold: float = 0.02,
) -> np.ndarray:
    """Поле нормализованного фона: каким фон был бы, если бы объекта не было.

    В чистом фоне это просто I / B (единица там, где фон ровный, и меньше единицы
    там, где отражение). Под объектом наблюдать нечего, поэтому значение
    достраивается от ближайшего чистого пикселя фона.

    Достраивать нужно ради узкой полосы кромки: там в композитинге участвует
    слагаемое (1 - alpha) * фон, и подставить туда наблюдаемый (уже смешанный
    с товаром) пиксель — значит вернуть ту самую цветную кайму, которую мы убираем.
    """
    ratio = img_lin / model.surface
    valid = alpha < bg_threshold

    if valid.all():
        return np.clip(ratio, 0.0, 1.0).astype(np.float32)
    if not valid.any():
        return np.ones_like(ratio)

    # Заполнение ближайшим соседом: на полосе в 1-3 пикселя это практически точно,
    # а глубоко под объектом значение всё равно домножается на (1 - alpha) ~ 0.
    idx = ndimage.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    filled = ratio[idx[0], idx[1]]
    out = np.where(valid[..., None], ratio, filled)
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def compose(
    img_lin: np.ndarray,
    alpha: np.ndarray,
    model: BackgroundModel,
    bg_ratio: np.ndarray,
    wb_factor: np.ndarray | None = None,
) -> np.ndarray:
    """Собирает результат: объект без цветной каймы поверх убелённого фона.

    Уравнение композитинга гласит  I = a*F + (1-a)*B, где F — чистый цвет товара.
    Отсюда обычно достают F = (I - (1-a)*B) / a, но делить на a опасно: на полупрозрачной
    кромке a близко к нулю и шум взрывается.

    Деление не нужно вовсе. В итоговую формулу входит не F, а произведение a*F,
    а оно равно (I - (1-a)*B) без всякого деления. Поэтому чистка кромки здесь
    численно устойчива по построению и не требует подбора эпсилон-порогов.
    """
    a = alpha[..., None].astype(np.float32)

    # a*F — вклад товара, уже очищенный от подмешанного фона.
    fg_premult = img_lin - (1.0 - a) * model.surface
    # Физический потолок: вклад не может быть ярче самого товара (F <= 1).
    fg_premult = np.clip(fg_premult, 0.0, a)

    if wb_factor is not None:
        fg_premult = fg_premult * wb_factor[None, None, :]

    return np.clip(fg_premult + (1.0 - a) * bg_ratio, 0.0, 1.0).astype(np.float32)


def protect_mask(alpha: np.ndarray, threshold: float = 0.5, grow: int = 3) -> np.ndarray:
    """Маска, которую нельзя трогать дотяжкой белого.

    Без неё белый товар на белом фоне схлопывается: светлая кожа сандалии уходит
    в 255 вместе с фоном, и товар теряет форму. Маска слегка расширяется, чтобы
    накрыть и кромку.
    """
    solid = alpha > threshold
    if grow > 0:
        solid = ndimage.binary_dilation(solid, iterations=int(grow))
    # Мягкий край, иначе на границе защиты появится ступенька.
    return np.clip(ndimage.gaussian_filter(solid.astype(np.float32), sigma=1.5), 0.0, 1.0)
