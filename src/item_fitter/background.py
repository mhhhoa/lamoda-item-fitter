"""Оценка модели фона и flat-field нормализация.

Это ядро решения. Идея: студийный фон — это гладкое поле освещённости B(x, y),
а отражение и контактная тень на полу — это то же поле, умноженное на коэффициент
меньше единицы. Поэтому деление кадра на B переводит чистый фон ровно в белый,
а отражение оставляет как пропорционально более тёмное — то есть серую тень на белом.

Отсюда главное свойство подхода: тень и отражение сохраняются сами собой, их не нужно
вырезать, дорисовывать или подкладывать отдельным слоем.

Ключевая трудность — сам фит B. Пиксели фона включают в себя отражения, которые темнее
чистого фона. Обычный МНК занизит модель, чистый фон после деления окажется светлее
единицы и выбьется в пересвет, а отражение исчезнет. Поэтому фит делается робастным
с АСИММЕТРИЧНОЙ отбраковкой: тёмные выбросы (отражения, тени) отсекаются агрессивно,
светлые — мягко. Модель идёт по верхней огибающей, то есть по чистому фону.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

__all__ = ["BackgroundModel", "fit_background", "normalize_background", "white_roll_off"]

# Фит считается по случайной подвыборке: на 3 Мпикс полный МНК избыточен,
# а 200k точек дают ту же поверхность. Seed фиксирован — прогон детерминирован.
_FIT_SAMPLE = 200_000
_SEED = 0


@dataclass
class BackgroundModel:
    """Результат фита фона."""

    surface: np.ndarray  # (H, W, 3) линейный RGB, модель чистого фона
    mean_color: np.ndarray  # (3,) средний линейный цвет фона
    residual_rms: float  # разброс чистого фона вокруг модели (мера гладкости)
    n_pixels_used: int  # сколько пикселей осталось после отбраковки
    degenerate: bool  # True, если фона было слишком мало для надёжного фита


def _poly_basis(h: int, w: int, degree: int) -> np.ndarray:
    """Полиномиальный базис по нормированным координатам, форма (h*w, n_terms).

    Координаты нормируются в [-1, 1], иначе при степени 3 обусловленность матрицы
    на кадре 1500x2000 разваливается.
    """
    v, u = np.meshgrid(
        np.linspace(-1.0, 1.0, h, dtype=np.float32),
        np.linspace(-1.0, 1.0, w, dtype=np.float32),
        indexing="ij",
    )
    terms = [
        (u**i) * (v**j)
        for total in range(degree + 1)
        for i in range(total + 1)
        for j in [total - i]
    ]
    return np.stack([t.ravel() for t in terms], axis=1)


def _weighted_lstsq(basis: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Взвешенный МНК через нормальные уравнения. basis (N, k), y (N,), w (N,)."""
    bw = basis * w[:, None]
    ata = basis.T @ bw
    atb = bw.T @ y
    # Тихоновская регуляризация: спасает, когда фона мало и базис вырождается.
    ata += np.eye(ata.shape[0], dtype=ata.dtype) * 1e-6
    return np.linalg.solve(ata, atb)


def fit_background(
    img_lin: np.ndarray,
    alpha: np.ndarray,
    degree: int = 2,
    iterations: int = 6,
    low_sigma: float = 1.2,
    high_sigma: float = 3.0,
    alpha_threshold: float = 0.02,
) -> BackgroundModel:
    """Строит гладкую модель чистого фона B(x, y) по пикселям вне объекта.

    Args:
        img_lin: (H, W, 3) линейный RGB [0, 1].
        alpha: (H, W) маска объекта [0, 1]. Фон — там, где alpha ~ 0.
        degree: степень полинома. 2 хватает почти всегда; 3 — для сложного градиента.
        iterations: число итераций отбраковки.
        low_sigma: порог отсечения СНИЗУ в сигмах. Маленький — агрессивно выкидывает
            отражения и тени, чтобы они не занижали модель. Это и есть асимметрия.
        high_sigma: порог отсечения СВЕРХУ. Больше low_sigma, потому что сверху
            отбрасывать почти нечего (разве что блик на полу).
        alpha_threshold: пиксели с alpha выше порога в фит не берутся.
    """
    h, w, _ = img_lin.shape
    basis_full = _poly_basis(h, w, degree)
    flat = img_lin.reshape(-1, 3)
    is_bg = alpha.reshape(-1) < alpha_threshold

    bg_idx = np.flatnonzero(is_bg)
    degenerate = bg_idx.size < max(2000, 0.02 * h * w)

    if bg_idx.size == 0:
        # Фона не нашлось вовсе: отдаём плоскую модель по медиане кадра,
        # чтобы пайплайн не падал, и помечаем результат как ненадёжный.
        med = np.median(flat, axis=0).astype(np.float32)
        surface = np.broadcast_to(med, (h, w, 3)).copy()
        return BackgroundModel(surface, med, float("inf"), 0, True)

    rng = np.random.default_rng(_SEED)
    if bg_idx.size > _FIT_SAMPLE:
        bg_idx = rng.choice(bg_idx, _FIT_SAMPLE, replace=False)

    sample_basis = basis_full[bg_idx]
    sample_vals = flat[bg_idx]

    coeffs = np.zeros((sample_basis.shape[1], 3), dtype=np.float32)
    residual_rms = 0.0
    n_used = int(bg_idx.size)

    for ch in range(3):
        y = sample_vals[:, ch].astype(np.float32)
        weights = np.ones_like(y)

        for it in range(iterations):
            coef = _weighted_lstsq(sample_basis, y, weights)
            resid = y - sample_basis @ coef
            # Робастная сигма по MAD: обычное std само уедет из-за отражений.
            mad = np.median(np.abs(resid - np.median(resid)))
            sigma = float(1.4826 * mad) or 1e-6
            if it < iterations - 1:
                keep = (resid > -low_sigma * sigma) & (resid < high_sigma * sigma)
                if keep.sum() < 500:  # отбраковали слишком много — откатываемся
                    break
                weights = keep.astype(np.float32)

        coeffs[:, ch] = coef
        kept = weights > 0
        residual_rms = max(residual_rms, float(np.sqrt(np.mean(resid[kept] ** 2))))
        n_used = min(n_used, int(kept.sum()))

    surface = (basis_full @ coeffs).reshape(h, w, 3).astype(np.float32)
    # Ниже этого порога деление превращается в усиление шума.
    surface = np.maximum(surface, 1e-3)

    return BackgroundModel(
        surface=surface,
        mean_color=surface.reshape(-1, 3).mean(axis=0),
        residual_rms=residual_rms,
        n_pixels_used=n_used,
        degenerate=degenerate,
    )


def normalize_background(
    img_lin: np.ndarray,
    model: BackgroundModel,
    reflection_strength: float = 1.0,
) -> np.ndarray:
    """Flat-field деление: фон -> белый, отражение -> серое на белом.

    reflection_strength: 1.0 — отражение как в оригинале, 0.0 — убрать полностью
    (объект будет «висеть в воздухе»). Промежуточные значения ослабляют тень.
    """
    norm = img_lin / model.surface
    if reflection_strength != 1.0:
        norm = 1.0 - (1.0 - norm) * reflection_strength
    return np.clip(norm, 0.0, 1.0).astype(np.float32)


def white_roll_off(
    srgb: np.ndarray,
    knee_low: float = 0.955,
    knee_high: float = 0.992,
    protect: np.ndarray | None = None,
    smooth_sigma: float = 2.0,
) -> np.ndarray:
    """Плавно дотягивает почти-белое до честного 255,255,255.

    Валидатор маркетплейса смотрит на углы кадра, а после деления фон получается
    не ровно 1.0, а 0.99 +/- шум. Жёсткий clip оставил бы видимую ступеньку там,
    где отражение переходит в фон, поэтому переход делается через smoothstep:
    ниже knee_low ничего не меняется, выше knee_high — ровно белый.

    Решение о дотяжке принимается по СГЛАЖЕННОЙ яркости, а не по самому пикселю.
    Причина: шум JPEG на чистом фоне разбрасывает значения на пару единиц, и
    отдельные пиксели не дотягиваются до порога — в углу вместо 255 остаётся 254,
    и кадр формально перестаёт соответствовать требованию белого фона. Отражение
    же — это пространственно связный градиент, сглаживание его не трогает, поэтому
    тень под товаром сохраняется как была.

    protect: (H, W) маска [0, 1]; где она равна 1, коррекция не применяется.
        Нужна для белого товара — белые сандалии на белом фоне иначе схлопнутся.
    """
    v = np.asarray(srgb, dtype=np.float32)
    # Ориентируемся на самый тёмный канал: иначе цветной, но светлый пиксель
    # (бледно-розовая кожа) частично побелеет.
    lo = v.min(axis=-1, keepdims=True)
    if smooth_sigma > 0:
        lo = ndimage.gaussian_filter(lo[..., 0], sigma=smooth_sigma)[..., None]

    t = np.clip((lo - knee_low) / max(knee_high - knee_low, 1e-6), 0.0, 1.0)
    s = t * t * (3.0 - 2.0 * t)
    if protect is not None:
        s = s * (1.0 - protect[..., None])

    return np.clip(v * (1.0 - s) + s, 0.0, 1.0).astype(np.float32)


def white_balance_factor(model: BackgroundModel, strength: float = 0.5) -> np.ndarray:
    """Множитель, снимающий цветной рефлекс фона с объекта.

    Цветной фон подсвечивает модель и товар: зелёная циклорама зеленит кожу ног,
    бежевая делает белые брюки кремовыми. Делить объект на B нельзя — пересветит,
    поэтому применяется только нейтрализация оттенка, с регулируемой силой.

    strength: 0.0 — не трогать объект, 1.0 — полностью снять оттенок фона.
        Значение по умолчанию консервативное; точное подбирает `fitter calibrate`
        по эталонным парам.
    """
    tint = model.mean_color / max(float(model.mean_color.mean()), 1e-6)
    factor = tint ** (-float(strength))
    # Нормируем по яркости, чтобы коррекция меняла только оттенок, а не экспозицию.
    lum = float(np.dot(factor, [0.2126, 0.7152, 0.0722]))
    return (factor / max(lum, 1e-6)).astype(np.float32)
