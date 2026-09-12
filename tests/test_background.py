"""Тесты ядра: flat-field нормализация фона.

Эти тесты ловят регрессии в самой математике. Синтетика строится так, чтобы
правильный ответ был известен заранее: фон обязан стать ровно белым, цвет товара
обязан остаться прежним, а отражение обязано выжить как серая тень.
"""

import numpy as np
import pytest

from item_fitter import background as bgmod
from item_fitter import colorspace as cs
from item_fitter import compose as comp


def _make_scene(
    h: int = 360,
    w: int = 280,
    bg_color=(0.95, 0.89, 0.84),  # тёплый бежевый, как в паре с сандалиями
    product_color=(0.42, 0.09, 0.17),  # бордо, как замшевые кроссовки
    with_reflection: bool = True,
):
    """Синтетическая сцена: градиентный цветной фон + товар + отражение под ним.

    Возвращает (sRGB кадр, alpha товара, бокс товара, бокс отражения).
    """
    v, u = np.meshgrid(
        np.linspace(-1.0, 1.0, h, dtype=np.float32),
        np.linspace(-1.0, 1.0, w, dtype=np.float32),
        indexing="ij",
    )
    # Неравномерный свет на циклораме: по центру ярче, к краям падает.
    shading = (1.0 - 0.18 * u**2 - 0.12 * v**2 + 0.06 * v).astype(np.float32)
    lin = np.asarray(bg_color, dtype=np.float32)[None, None, :] * shading[..., None]

    y0, y1, x0, x1 = int(h * 0.30), int(h * 0.60), int(w * 0.30), int(w * 0.70)
    lin[y0:y1, x0:x1] = np.asarray(product_color, dtype=np.float32)

    ry0, ry1 = y1, min(int(h * 0.72), h)
    if with_reflection:
        # Отражение — это тот же фон, умноженный на коэффициент < 1, затухающий вниз.
        fade = np.linspace(0.55, 1.0, ry1 - ry0, dtype=np.float32)[:, None, None]
        lin[ry0:ry1, x0:x1] *= fade

    alpha = np.zeros((h, w), dtype=np.float32)
    alpha[y0:y1, x0:x1] = 1.0

    return cs.linear_to_srgb(np.clip(lin, 0, 1)), alpha, (y0, y1, x0, x1), (ry0, ry1, x0, x1)


def _run(srgb, alpha, degree=2, reflection_strength=1.0, wb_strength=0.0):
    """Прогоняет сцену по той же цепочке модулей, что и боевой пайплайн.

    Деление на модель фона применяется ТОЛЬКО к фону: товар собирается отдельно
    через compose. Если делить весь кадр целиком, товар пересвечивает и перекрашивает.
    """
    lin = cs.srgb_to_linear(srgb)
    model = bgmod.fit_background(lin, alpha, degree=degree)

    ratio = comp.background_ratio_field(lin, model, alpha)
    if reflection_strength != 1.0:
        ratio = 1.0 - (1.0 - ratio) * reflection_strength

    wb = bgmod.white_balance_factor(model, wb_strength) if wb_strength else None
    out = cs.linear_to_srgb(comp.compose(lin, alpha, model, ratio, wb))
    return bgmod.white_roll_off(out, protect=comp.protect_mask(alpha)), model


def test_flat_background_becomes_pure_white():
    """Ровный градиентный фон обязан стать честным 255,255,255 во всех углах."""
    srgb, alpha, _, _ = _make_scene()
    out, model = _run(srgb, alpha)
    out8 = np.round(out * 255).astype(int)

    h, w = alpha.shape
    corners = [out8[0, 0], out8[0, w - 1], out8[h - 1, 0], out8[h - 1, w - 1]]
    for c in corners:
        assert tuple(c) == (255, 255, 255), f"угол не побелел: {c}"

    assert not model.degenerate
    # Модель должна лечь на гладкий фон почти идеально.
    assert model.residual_rms < 0.01, f"фит фона неточен: rms={model.residual_rms}"


def test_product_colour_survives():
    """Цвет товара не должен уехать: это главное требование маркетплейса."""
    srgb, alpha, (y0, y1, x0, x1), _ = _make_scene()
    out, _ = _run(srgb, alpha)

    pad = 4  # отступ от кромки, чтобы не мерить полосу смешивания
    before = srgb[y0 + pad : y1 - pad, x0 + pad : x1 - pad]
    after = out[y0 + pad : y1 - pad, x0 + pad : x1 - pad]

    de = cs.delta_e_2000(cs.rgb_to_lab(before), cs.rgb_to_lab(after))
    assert float(de.mean()) < 1.0, f"товар перекрасило: средний dE2000={de.mean():.2f}"


def test_reflection_is_kept_and_neutralised():
    """Отражение обязано выжить как СЕРАЯ тень, а не исчезнуть и не остаться бежевым."""
    srgb, alpha, _, (ry0, ry1, x0, x1) = _make_scene()
    out, _ = _run(srgb, alpha)

    band = out[ry0 + 2 : ry0 + 12, x0 + 6 : x1 - 6]
    assert float(band.mean()) < 0.93, "отражение пропало — объект повис в воздухе"

    # Нейтральность: разброс между каналами должен быть мал, иначе тень цветная.
    spread = float(np.abs(band.max(axis=-1) - band.min(axis=-1)).mean())
    assert spread < 0.035, f"тень осталась цветной, разброс каналов={spread:.3f}"


def test_reflection_strength_zero_removes_shadow():
    """Ползунок силы отражения на нуле обязан давать полностью чистый белый фон."""
    srgb, alpha, _, (ry0, ry1, x0, x1) = _make_scene()
    out, _ = _run(srgb, alpha, reflection_strength=0.0)

    band = out[ry0 + 2 : ry0 + 12, x0 + 6 : x1 - 6]
    assert float(band.min()) > 0.99, "отражение не убралось при strength=0"


def test_fit_ignores_reflection_darkening():
    """Асимметричная отбраковка: наличие отражения не должно занижать модель фона.

    Это и есть причина, по которой обычный МНК тут не годится.
    """
    clean, alpha, _, _ = _make_scene(with_reflection=False)
    dirty, _, _, _ = _make_scene(with_reflection=True)

    m_clean = bgmod.fit_background(cs.srgb_to_linear(clean), alpha)
    m_dirty = bgmod.fit_background(cs.srgb_to_linear(dirty), alpha)

    drift = float(np.abs(m_clean.surface - m_dirty.surface).max())
    assert drift < 0.02, f"отражение утянуло модель фона вниз на {drift:.4f}"


def test_white_roll_off_protects_masked_area():
    """Белый товар под защитной маской не должен схлопнуться в фон.

    0.995 — реалистичное значение чистого фона после деления: в теории ровно 1.0,
    на практике чуть ниже из-за шума JPEG.
    """
    img = np.full((20, 20, 3), 0.995, dtype=np.float32)
    protect = np.zeros((20, 20), dtype=np.float32)
    protect[5:15, 5:15] = 1.0

    out = bgmod.white_roll_off(img, protect=protect)
    assert out[0, 0, 0] == pytest.approx(1.0, abs=1e-5), "фон не дотянуло до белого"
    assert out[10, 10, 0] == pytest.approx(0.995, abs=1e-5), "защищённый товар выбелило"


def test_white_roll_off_leaves_reflection_alone():
    """Дотяжка белого не должна съедать полутона отражения."""
    img = np.full((8, 8, 3), 0.90, dtype=np.float32)
    assert bgmod.white_roll_off(img)[0, 0, 0] == pytest.approx(0.90, abs=1e-5)


def test_edge_decontamination_removes_colour_fringe():
    """Кромка товара не должна сохранять подмешанный цвет фона.

    Строим пиксель-полупрозрачную кромку: половина белого товара, половина бежевого
    фона. Наивная подстановка белого оставила бы там кремовый ореол.
    """
    h = w = 64
    bg_lin = np.full((h, w, 3), 0.0, dtype=np.float32)
    bg_lin[:] = np.array([0.95, 0.80, 0.66], dtype=np.float32)  # выраженный тёплый фон

    product = np.array([0.90, 0.90, 0.90], dtype=np.float32)  # нейтрально-белый товар
    alpha = np.zeros((h, w), dtype=np.float32)
    alpha[20:44, 20:44] = 1.0
    alpha[19, 20:44] = alpha[44, 20:44] = 0.5  # полупрозрачная кромка сверху и снизу

    lin = bg_lin * (1 - alpha[..., None]) + product * alpha[..., None]

    model = bgmod.fit_background(lin, alpha)
    ratio = comp.background_ratio_field(lin, model, alpha)
    out = comp.compose(lin, alpha, model, ratio)

    edge = out[19, 24:40]
    spread = float(np.abs(edge.max(axis=-1) - edge.min(axis=-1)).mean())
    assert spread < 0.02, f"на кромке осталась цветная кайма, разброс каналов={spread:.3f}"


def test_degenerate_when_no_background():
    """Если объект занимает весь кадр, это должно честно помечаться, а не падать."""
    srgb, _, _, _ = _make_scene()
    alpha = np.ones(srgb.shape[:2], dtype=np.float32)

    model = bgmod.fit_background(cs.srgb_to_linear(srgb), alpha)
    assert model.degenerate
    assert model.surface.shape == srgb.shape
