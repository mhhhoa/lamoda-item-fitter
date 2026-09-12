"""Сверка с эталонами подрядчика и автоподбор параметров.

Зачем: обработку сейчас делает внешний подрядчик, и переход на свой инструмент
нужно чем-то обосновать. Здесь считается, насколько наш результат отличается от
эталонного — численно, а не «на глаз».

Ожидаемая раскладка папки:
    samples/
        12345_before.jpg   исходник с цветным фоном
        12345_after.jpg    что вернул подрядчик
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from .colorspace import delta_e_2000, load_srgb, rgb_to_lab
from .config import Settings
from .matting import get_backend
from .pipeline import process_array

__all__ = ["find_pairs", "compare_pair", "compare_folder", "calibrate", "PairScore"]

_BEFORE = ("_before", "_до", "-before", "_src", "_in")
_AFTER = ("_after", "_после", "-after", "_dst", "_out")


@dataclass
class PairScore:
    name: str
    delta_e_mean: float
    delta_e_p95: float
    delta_e_product: float
    delta_e_background: float
    ssim: float
    ours: np.ndarray
    reference: np.ndarray
    source: np.ndarray
    verdict: str


def find_pairs(folder: str | Path) -> list[tuple[str, Path, Path]]:
    """Находит пары (артикул, до, после) по суффиксам в именах файлов."""
    folder = Path(folder)
    befores: dict[str, Path] = {}
    afters: dict[str, Path] = {}

    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        stem = p.stem.lower()
        for suf in _BEFORE:
            if stem.endswith(suf):
                befores[stem[: -len(suf)]] = p
                break
        else:
            for suf in _AFTER:
                if stem.endswith(suf):
                    afters[stem[: -len(suf)]] = p
                    break

    return [(k, befores[k], afters[k]) for k in sorted(befores.keys() & afters.keys())]


def _match_size(img: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Приводит эталон к размеру нашего результата, если подрядчик менял геометрию."""
    if img.shape[:2] == shape:
        return img
    pil = Image.fromarray(np.round(np.clip(img, 0, 1) * 255).astype(np.uint8), "RGB")
    pil = pil.resize((shape[1], shape[0]), Image.LANCZOS)
    return np.asarray(pil, dtype=np.float32) / 255.0


def _ssim(a: np.ndarray, b: np.ndarray, win: int = 7) -> float:
    """SSIM по яркости. Локальная реализация, чтобы не тянуть scikit-image."""
    ga = a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    gb = b @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    c1, c2 = 0.01**2, 0.03**2
    f = lambda x: ndimage.uniform_filter(x, win)  # noqa: E731
    mu_a, mu_b = f(ga), f(gb)
    saa = f(ga * ga) - mu_a * mu_a
    sbb = f(gb * gb) - mu_b * mu_b
    sab = f(ga * gb) - mu_a * mu_b
    num = (2 * mu_a * mu_b + c1) * (2 * sab + c2)
    den = (mu_a**2 + mu_b**2 + c1) * (saa + sbb + c2)
    return float(np.mean(num / np.maximum(den, 1e-12)))


def compare_pair(
    before_path: Path,
    after_path: Path,
    settings: Settings,
    name: str = "",
    matte_fn=None,
    alpha: np.ndarray | None = None,
) -> PairScore:
    """Прогоняет «до» через пайплайн и сравнивает с эталонным «после»."""
    src, _ = load_srgb(before_path)
    ref, _ = load_srgb(after_path)

    res = process_array(src, settings, matte_fn=matte_fn, alpha=alpha)
    ours = res.image
    ref = _match_size(ref, ours.shape[:2])

    de = delta_e_2000(rgb_to_lab(ours), rgb_to_lab(ref))
    core = ndimage.binary_erosion(res.alpha > 0.9, iterations=3)
    bg = res.alpha < 0.02

    mean = float(de.mean())
    return PairScore(
        name=name or before_path.stem,
        delta_e_mean=round(mean, 2),
        delta_e_p95=round(float(np.percentile(de, 95)), 2),
        delta_e_product=round(float(de[core].mean()), 2) if core.sum() > 100 else float("nan"),
        delta_e_background=round(float(de[bg].mean()), 2) if bg.sum() > 100 else float("nan"),
        ssim=round(_ssim(ours, ref), 4),
        ours=ours,
        reference=ref,
        source=src,
        # ΔE2000 < 2 — различимо только при прямом сравнении встык;
        # < 3 — практически неразличимо в карточке; выше — видно.
        verdict="совпадает" if mean < 2.0 else ("близко" if mean < 3.5 else "расходится"),
    )


def compare_folder(folder: str | Path, settings: Settings) -> list[PairScore]:
    pairs = find_pairs(folder)
    if not pairs:
        raise FileNotFoundError(
            f"В {folder} не найдено ни одной пары. Ожидаются файлы вида "
            f"«артикул_before.jpg» и «артикул_after.jpg»."
        )
    matte_fn = get_backend(settings.matting)
    return [compare_pair(b, a, settings, name=k, matte_fn=matte_fn) for k, b, a in pairs]


# --- автокалибровка ---------------------------------------------------------

DEFAULT_GRID = {
    "wb_strength": [0.0, 0.25, 0.5, 0.75, 1.0],
    "knee_low": [0.930, 0.955, 0.975],
    "poly_degree": [2, 3],
}


def calibrate(
    folder: str | Path,
    base: Settings,
    grid: dict | None = None,
    progress=None,
) -> tuple[Settings, list[tuple[dict, float]]]:
    """Подбирает параметры так, чтобы результат максимально сошёлся с эталонами.

    Матирование не зависит от перебираемых параметров, поэтому маски считаются
    один раз на кадр и переиспользуются: иначе перебор из 30 комбинаций означал бы
    30 прогонов нейросети на каждый кадр.

    Возвращает (лучшие настройки, отсортированный список всех комбинаций).
    """
    grid = grid or DEFAULT_GRID
    pairs = find_pairs(folder)
    if not pairs:
        raise FileNotFoundError(f"В {folder} не найдено пар «_before» / «_after».")

    matte_fn = get_backend(base.matting)
    cache = {}
    for key, before, _after in pairs:
        src, _ = load_srgb(before)
        cache[key] = np.clip(matte_fn(src), 0.0, 1.0).astype(np.float32)

    keys = list(grid)
    combos = list(itertools.product(*(grid[k] for k in keys)))
    scored: list[tuple[dict, float]] = []

    for i, values in enumerate(combos, start=1):
        params = dict(zip(keys, values))
        trial = base.replace(**params)
        scores = [
            compare_pair(b, a, trial, name=k, alpha=cache[k]).delta_e_mean for k, b, a in pairs
        ]
        mean = float(np.mean(scores))
        scored.append((params, round(mean, 3)))
        if progress:
            progress(i, len(combos), params, mean)

    scored.sort(key=lambda x: x[1])
    return base.replace(**scored[0][0]), scored
