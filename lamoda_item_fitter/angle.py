"""Определение ракурса по силуэту товара.

Пороги выведены из 19 фото, прошедших модерацию Ламоды (см. reference/).
Ракурс ни на масштаб, ни на выравнивание не влияет — эталоны показали, что
геометрия от него не зависит. Это подсказка оператору и метка в отчёте.

Чего силуэт не умеет: отличить вид сбоку от вида подошвы. У них совпадает
контур — вытянутое пятно с плоским низом, и ни текстура, ни симметрия их
не разделяют. Поэтому такие кадры объединены в один класс «профильный».
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SIDE_OR_SOLE = "profile"
PAIR = "pair"
FRONT_BACK = "front_back"
TOP = "top"
OTHER = "other"

LABELS = {
    SIDE_OR_SOLE: "Вид сбоку / подошва",
    PAIR: "Пара 3/4",
    FRONT_BACK: "Спереди / сзади",
    TOP: "Вид сверху",
    OTHER: "Другой ракурс",
}


@dataclass(frozen=True)
class AngleResult:
    kind: str
    confidence: float
    aspect: float
    bottom_flatness: float
    contact_ratio: float
    symmetry: float
    components: int

    @property
    def label(self) -> str:
        return LABELS.get(self.kind, LABELS[OTHER])


def _features(mask: np.ndarray) -> tuple[float, float, float, float]:
    height, width = mask.shape
    aspect = width / height if height else 0.0

    columns = mask.any(axis=0)
    if not columns.any():
        return aspect, 1.0, 0.0, 0.0
    bottom = (height - 1 - np.argmax(mask[::-1], axis=0)).astype(np.float64)[columns] / height
    # разброс нижней кромки: у профильного кадра обувь стоит на ровной подошве,
    # у пары под углом низ «рваный» — это и разделяет классы
    bottom_flatness = float(bottom.std())

    band = mask[int(height * 0.97):]
    contact_ratio = float(band.any(axis=0).sum() / width) if width else 0.0

    mirrored = mask[:, ::-1]
    union = (mask | mirrored).sum()
    symmetry = float((mask & mirrored).sum() / union) if union else 0.0
    return aspect, bottom_flatness, contact_ratio, symmetry


def _margin(value: float, low: float, high: float) -> float:
    """Насколько уверенно значение лежит внутри коридора (0 — на границе)."""
    if high <= low:
        return 0.0
    return float(np.clip(min(value - low, high - value) / ((high - low) / 2), 0.0, 1.0))


def classify(mask: np.ndarray, bbox: tuple[int, int, int, int], components: int) -> AngleResult:
    """Классифицирует ракурс по силуэту в габарите товара."""
    x0, y0, x1, y1 = bbox
    crop = mask[y0:y1 + 1, x0:x1 + 1]
    aspect, flat, contact, symmetry = _features(crop)

    if components >= 2:
        return AngleResult(PAIR, 0.9, aspect, flat, contact, symmetry, components)

    if aspect >= 1.8 and flat < 0.08:
        confidence = 0.5 + 0.5 * min(_margin(aspect, 1.8, 3.4), _margin(flat, -0.08, 0.08))
        return AngleResult(SIDE_OR_SOLE, confidence, aspect, flat, contact, symmetry, components)

    if 1.05 <= aspect < 1.8 and flat >= 0.09:
        confidence = 0.4 + 0.4 * _margin(aspect, 1.0, 1.85)
        return AngleResult(PAIR, confidence, aspect, flat, contact, symmetry, components)

    if aspect < 1.05:
        kind = TOP if symmetry > 0.9 else FRONT_BACK
        confidence = 0.4 + 0.5 * abs(symmetry - 0.9) / 0.9
        return AngleResult(kind, min(confidence, 0.9), aspect, flat, contact, symmetry, components)

    return AngleResult(OTHER, 0.2, aspect, flat, contact, symmetry, components)
