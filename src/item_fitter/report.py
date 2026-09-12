"""Самодостаточный HTML-отчёт по пакетному прогону.

Превью кладутся внутрь файла как data-URI, поэтому отчёт — это один .html,
который можно переслать руководителю или закинуть в чат, ничего не прикладывая.

Кадры сортируются худшими вверх: смысл отчёта в том, чтобы глазами смотреть
не весь пакет, а только то, что инструмент сам пометил.
"""

from __future__ import annotations

import base64
import html
import io
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from .pipeline import ProcessResult
from .qa import CHECK, FAIL, OK

__all__ = ["write_report"]

_ORDER = {FAIL: 0, CHECK: 1, OK: 2}
_LABEL = {FAIL: "ОШИБКА", CHECK: "ПРОВЕРИТЬ", OK: "ГОТОВО"}

_CSS = """
*{box-sizing:border-box}
body{margin:0;padding:24px;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
     background:#f6f7f9;color:#16181d}
h1{font-size:20px;margin:0 0 4px}
.sub{color:#6b7280;margin-bottom:20px}
.tally{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:24px}
.pill{padding:8px 14px;border-radius:999px;font-weight:600;font-size:13px}
.pill.ok{background:#dcfce7;color:#166534}
.pill.check{background:#fef3c7;color:#92400e}
.pill.fail{background:#fee2e2;color:#991b1b}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin-bottom:14px}
.card.fail{border-left:4px solid #dc2626}
.card.check{border-left:4px solid #d97706}
.card.ok{border-left:4px solid #16a34a}
.head{display:flex;justify-content:space-between;align-items:center;gap:12px;
      flex-wrap:wrap;margin-bottom:12px}
.name{font-weight:600;word-break:break-all}
.badge{font-size:11px;font-weight:700;padding:3px 9px;border-radius:5px;white-space:nowrap}
.badge.ok{background:#dcfce7;color:#166534}
.badge.check{background:#fef3c7;color:#92400e}
.badge.fail{background:#fee2e2;color:#991b1b}
.shots{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
figure{margin:0}
figure img{display:block;width:200px;max-width:100%;border:1px solid #e5e7eb;border-radius:6px;
           background:repeating-conic-gradient(#eee 0 25%,#fff 0 50%) 50%/14px 14px}
figcaption{font-size:11px;color:#6b7280;margin-top:4px;text-align:center}
.notes{margin:0 0 12px;padding-left:18px}
.notes li{color:#92400e;margin-bottom:3px}
table{border-collapse:collapse;font-size:12px;width:100%}
td{padding:3px 12px 3px 0;color:#4b5563;vertical-align:top}
td.k{color:#9ca3af;white-space:nowrap}
.foot{color:#9ca3af;font-size:12px;margin-top:24px}
@media(max-width:520px){figure img{width:100%}}
"""


def _thumb(arr: np.ndarray, width: int = 200) -> str:
    """Уменьшенное превью как data-URI."""
    a = np.clip(np.asarray(arr, dtype=np.float32), 0.0, 1.0)
    if a.ndim == 2:
        a = np.repeat(a[..., None], 3, axis=-1)
    img = Image.fromarray(np.round(a * 255).astype(np.uint8), "RGB")
    if img.width > width:
        img = img.resize((width, max(1, round(img.height * width / img.width))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _metrics_rows(metrics: dict) -> str:
    pretty = {
        "bg_corner_min": "Фон в углах (справочно, 0–255)",
        "product_delta_e": "Сдвиг цвета товара, ΔE2000",
        "product_delta_e_p95": "Сдвиг цвета, 95-й перцентиль",
        "bg_residual": "Разброс фона вокруг модели",
        "blown_ratio": "Доля товара, выбеленного до фона",
        "mask_filled_px": "Починено точек маски внутри товара",
        "mask_removed_px": "Убрано ложных точек товара из фона",
        "reflection_before": "Площадь отражения до",
        "reflection_after": "Площадь отражения после",
        "alpha_area": "Доля кадра, занятая товаром",
        "alpha_edge_touch": "Товар на краю кадра",
        "file_kb": "Размер файла, КБ",
    }
    rows = [
        f"<tr><td class='k'>{html.escape(label)}</td><td>{html.escape(str(metrics[key]))}</td></tr>"
        for key, label in pretty.items()
        if metrics.get(key) is not None
    ]
    return "<table>" + "".join(rows) + "</table>"


def write_report(
    path: str | Path,
    results: list[ProcessResult],
    failures: list[tuple[Path, Exception]] | None = None,
    preset_name: str = "",
) -> Path:
    """Пишет HTML-отчёт. Возвращает путь к файлу."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    failures = failures or []

    ordered = sorted(results, key=lambda r: (_ORDER[r.verdict], str(r.source)))
    tally = {v: sum(1 for r in results if r.verdict == v) for v in (FAIL, CHECK, OK)}

    parts: list[str] = [
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>Отчёт по замене фона</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>Отчёт по замене фона на белый</h1>",
        f"<div class='sub'>{datetime.now():%d.%m.%Y %H:%M}"
        + (f" &middot; пресет <b>{html.escape(preset_name)}</b>" if preset_name else "")
        + f" &middot; кадров: {len(results) + len(failures)}</div>",
        "<div class='tally'>",
        f"<span class='pill ok'>Готово без замечаний: {tally[OK]}</span>",
        f"<span class='pill check'>Проверить глазами: {tally[CHECK]}</span>",
        f"<span class='pill fail'>Ошибки: {tally[FAIL] + len(failures)}</span>",
        "</div>",
    ]

    for src, exc in failures:
        parts.append(
            f"<div class='card fail'><div class='head'><span class='name'>{html.escape(src.name)}"
            f"</span><span class='badge fail'>НЕ ОБРАБОТАН</span></div>"
            f"<div style='color:#991b1b'>{html.escape(type(exc).__name__)}: "
            f"{html.escape(str(exc)[:400])}</div></div>"
        )

    for r in ordered:
        cls = r.verdict.lower()
        name = r.source.name if r.source else "(без имени)"
        notes = (
            "<ul class='notes'>"
            + "".join(f"<li>{html.escape(n)}</li>" for n in r.report.notes)
            + "</ul>"
            if r.report.notes
            else ""
        )
        parts.append(
            f"<div class='card {cls}'>"
            f"<div class='head'><span class='name'>{html.escape(name)}</span>"
            f"<span class='badge {cls}'>{_LABEL[r.verdict]}</span></div>"
            "<div class='shots'>"
            f"<figure><img src='{_thumb(r.original)}' alt=''><figcaption>до</figcaption></figure>"
            f"<figure><img src='{_thumb(r.image)}' alt=''><figcaption>после</figcaption></figure>"
            f"<figure><img src='{_thumb(r.alpha)}' alt=''><figcaption>маска товара</figcaption></figure>"
            "</div>"
            f"{notes}{_metrics_rows(r.report.metrics)}</div>"
        )

    parts.append(
        "<div class='foot'>Смотреть глазами нужно карточки, помеченные "
        "«ПРОВЕРИТЬ» и «ОШИБКА». Остальные прошли автоматические проверки: фон вышел "
        "в белый, цвет товара не сдвинулся, отражение сохранено.</div></body></html>"
    )

    path.write_text("".join(parts), encoding="utf-8")
    return path


_COMPARE_CSS = _CSS + """
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start}
.score{font-size:22px;font-weight:700}
.score.good{color:#166534}.score.mid{color:#92400e}.score.bad{color:#991b1b}
"""


def write_compare_report(path, scores, preset_name: str = ""):
    """Отчёт по сверке с эталонами подрядчика.

    Показывает рядом три кадра: исходник, наш результат и то, что вернул подрядчик,
    плюс численное расхождение. Это то, что можно показать руководителю вместо слов
    «получилось не хуже».
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(scores, key=lambda s: -s.delta_e_mean)
    overall = float(np.mean([s.delta_e_mean for s in scores])) if scores else float("nan")

    def cls(v: float) -> str:
        return "good" if v < 2.0 else ("mid" if v < 3.5 else "bad")

    parts = [
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>Сверка с эталонами</title>",
        f"<style>{_COMPARE_CSS}</style></head><body>",
        "<h1>Сверка нашей обработки с эталонами подрядчика</h1>",
        f"<div class='sub'>{datetime.now():%d.%m.%Y %H:%M}"
        + (f" &middot; пресет <b>{html.escape(preset_name)}</b>" if preset_name else "")
        + f" &middot; пар: {len(scores)}</div>",
        f"<div class='tally'><span class='pill ok'>Среднее расхождение по всем парам: "
        f"ΔE2000 = {overall:.2f}</span></div>",
        "<div class='card'><b>Как читать ΔE2000.</b> Меньше 1 — отличие неразличимо глазом. "
        "1–2 — заметно только если положить кадры встык. 2–3,5 — практически неразличимо "
        "в карточке товара. Больше 5 — видно сразу.</div>",
    ]

    for s in ordered:
        parts.append(
            f"<div class='card'><div class='head'><span class='name'>{html.escape(s.name)}</span>"
            f"<span class='score {cls(s.delta_e_mean)}'>ΔE {s.delta_e_mean} &middot; "
            f"{html.escape(s.verdict)}</span></div>"
            "<div class='shots'>"
            f"<figure><img src='{_thumb(s.source)}'><figcaption>исходник</figcaption></figure>"
            f"<figure><img src='{_thumb(s.ours)}'><figcaption>наш результат</figcaption></figure>"
            f"<figure><img src='{_thumb(s.reference)}'><figcaption>подрядчик</figcaption></figure>"
            "</div>"
            "<table>"
            f"<tr><td class='k'>Расхождение на товаре</td><td>{s.delta_e_product}</td></tr>"
            f"<tr><td class='k'>Расхождение на фоне</td><td>{s.delta_e_background}</td></tr>"
            f"<tr><td class='k'>95-й перцентиль</td><td>{s.delta_e_p95}</td></tr>"
            f"<tr><td class='k'>Структурное сходство SSIM</td><td>{s.ssim}</td></tr>"
            "</table></div>"
        )

    parts.append("</body></html>")
    path.write_text("".join(parts), encoding="utf-8")
    return path
