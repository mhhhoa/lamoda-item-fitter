"""Метрики качества и автоматический вердикт по кадру.

Смысл модуля — не «оценить красоту», а сузить ручную проверку. На потоке
300+ кадров в неделю глазами всё не пересмотреть, поэтому каждый кадр получает
вердикт OK / CHECK / FAIL, и в отчёте наверх всплывает только проблемное.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from .background import BackgroundModel
from .colorspace import delta_e_2000, rgb_to_lab
from .config import Settings

__all__ = ["QAReport", "evaluate"]

OK, CHECK, FAIL = "OK", "CHECK", "FAIL"


@dataclass
class QAReport:
    verdict: str = OK
    metrics: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def worsen(self, level: str, note: str) -> None:
        """Понижает вердикт до level и записывает причину."""
        order = {OK: 0, CHECK: 1, FAIL: 2}
        if order[level] > order[self.verdict]:
            self.verdict = level
        self.notes.append(note)


def _corner_min(srgb: np.ndarray, patch: int = 24) -> int:
    """Минимальное значение канала по четырём углам, в шкале 0..255.

    Именно углы смотрит валидатор маркетплейса, когда проверяет «белый ли фон».

    Округление здесь принципиально: мерить нужно ровно то значение, которое уйдёт
    в 8-битный файл. Отбрасывание дробной части давало бы 254 там, где в JPEG
    на самом деле записывается 255, и отчёт врал бы на ровном месте.
    """
    h, w, _ = srgb.shape
    p = max(2, min(patch, h // 8, w // 8))
    corners = [
        srgb[:p, :p],
        srgb[:p, w - p :],
        srgb[h - p :, :p],
        srgb[h - p :, w - p :],
    ]
    return int(min(np.round(float(c.min()) * 255.0) for c in corners))


def evaluate(
    before: np.ndarray,
    after: np.ndarray,
    alpha: np.ndarray,
    model: BackgroundModel,
    settings: Settings,
) -> QAReport:
    """Считает метрики и выносит вердикт. before/after — sRGB [0,1] одного размера."""
    rep = QAReport()
    h, w = alpha.shape
    m = rep.metrics

    # --- фон вышел в белый? ---
    # Пара единиц недо-белизны в углу роли не играет: важно, что фон белый на вид,
    # а не что он ровно 255. Поэтому это никогда не ошибка, а замечание, и только
    # когда фон отличается заметно.
    m["bg_corner_min"] = _corner_min(after)
    if m["bg_corner_min"] < settings.min_white:
        rep.worsen(
            CHECK,
            f"Фон в углах заметно не белый ({m['bg_corner_min']} из 255).",
        )

    # --- фон вообще был гладким? ---
    m["bg_residual"] = round(float(model.residual_rms), 5)
    if model.degenerate:
        rep.worsen(FAIL, "Объект занимает почти весь кадр — чистого фона для модели не осталось.")
    elif model.residual_rms > settings.max_bg_residual:
        rep.worsen(
            CHECK,
            f"Фон неоднородный (разброс {model.residual_rms:.3f}). "
            f"Похоже на сюжетный кадр, а не гладкую циклораму.",
        )

    # --- цвет товара не уехал? самое важное для карточки ---
    core = ndimage.binary_erosion(alpha > 0.9, iterations=3)
    m["product_px"] = int(core.sum())
    if core.sum() > 200:
        de = delta_e_2000(rgb_to_lab(before[core]), rgb_to_lab(after[core]))
        m["product_delta_e"] = round(float(de.mean()), 2)
        m["product_delta_e_p95"] = round(float(np.percentile(de, 95)), 2)
        if m["product_delta_e"] > settings.max_product_delta_e * 1.7:
            rep.worsen(FAIL, f"Цвет товара сильно уехал (ΔE2000 {m['product_delta_e']}).")
        elif m["product_delta_e"] > settings.max_product_delta_e:
            rep.worsen(CHECK, f"Цвет товара заметно сдвинулся (ΔE2000 {m['product_delta_e']}).")
    else:
        m["product_delta_e"] = None
        rep.worsen(CHECK, "Маска товара слишком мелкая — проверить, что объект найден верно.")

    # --- светлый товар не схлопнулся с белым фоном? ---
    if core.sum() > 200:
        was_ok = before[core].max(axis=-1) < 0.99
        now_blown = after[core].min(axis=-1) > 0.995
        m["blown_ratio"] = round(float((was_ok & now_blown).mean()), 4)
        if m["blown_ratio"] > settings.max_blown_ratio:
            rep.worsen(
                CHECK,
                f"{m['blown_ratio']*100:.1f}% товара выбелило до фона — светлый товар "
                f"теряет форму. Понизьте knee_low.",
            )

    # --- отражение выжило? ---
    bg = alpha < 0.02
    if bg.sum() > 1000:
        ratio_before = (before[bg] / np.clip(model.surface[bg], 1e-3, None)).min(axis=-1)
        shade_before = float((ratio_before < 0.97).mean())
        shade_after = float((after[bg].min(axis=-1) < 0.97).mean())
        m["reflection_before"] = round(shade_before, 4)
        m["reflection_after"] = round(shade_after, 4)
        if shade_before > 0.005 and shade_after < shade_before * 0.4:
            rep.worsen(CHECK, "Отражение под товаром почти исчезло — объект «висит в воздухе».")

    # --- товар не обрезан краем кадра? ---
    border = np.zeros((h, w), bool)
    border[0, :] = border[-1, :] = border[:, 0] = border[:, -1] = True
    m["alpha_edge_touch"] = round(float((alpha[border] > 0.5).mean()), 4)
    if m["alpha_edge_touch"] > 0.25:
        rep.worsen(CHECK, "Объект заметно упирается в край кадра — проверьте кадрирование.")

    m["alpha_area"] = round(float((alpha > 0.5).mean()), 4)
    return rep


def verify_written_file(path, settings: Settings, rep: QAReport) -> QAReport:
    """Перепроверяет углы по РЕАЛЬНО записанному файлу.

    Между массивом в памяти и файлом на диске стоит сжатие JPEG, и оно способно
    сдвинуть значения на краю кадра. Проверять белизну фона по памяти — значит
    обещать то, чего в отгружаемом файле может не быть, поэтому итоговая цифра
    в отчёте берётся из самого файла.
    """
    from .colorspace import load_srgb

    written, _ = load_srgb(path)
    actual = _corner_min(written)
    rep.metrics["bg_corner_min"] = actual

    # Снимаем прежнюю пометку про углы: она была основана на данных в памяти.
    rep.notes = [n for n in rep.notes if "в углах заметно не белый" not in n]
    if actual < settings.min_white:
        rep.worsen(CHECK, f"Фон в углах заметно не белый ({actual} из 255).")
    return rep
