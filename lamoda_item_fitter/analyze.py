"""Калибратор: замер уже опубликованных фото, чтобы выверять пресет.

Этим инструментом получены значения в presets/lamoda.json. Если Ламода
поменяет требования, прогон по свежей пачке опубликованных фото покажет новые
цифры — и править нужно будет пресет, а не код.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median

import numpy as np
from PIL import Image

from . import angle as angle_mod
from .background import difference_map, estimate_background
from .config import Preset
from .imageio import is_supported, load_image
from .mask import background_variation, build_masks


@dataclass
class Measurement:
    name: str
    width: int
    height: int
    canvas_matches: bool
    background: tuple[int, int, int]
    background_spread: float
    threshold: int
    angle_kind: str
    angle_label: str
    cropped_sides: list[str] = field(default_factory=list)
    #: отступы по плотной маске, приведённые к холсту пресета
    margins: dict[str, float] = field(default_factory=dict)
    #: отступы по мягкой маске — показывают, где проходит край тени
    soft_margins: dict[str, float] = field(default_factory=dict)
    fill_width: float = 0.0
    fill_height: float = 0.0
    center_offset: float = 0.0
    shadow_px: int = 0
    shadow_confirmed: bool = False

    @property
    def fitted(self) -> bool:
        return not self.cropped_sides


def measure_file(path: Path, preset: Preset) -> Measurement | None:
    """Замеряет одно опубликованное фото."""
    image = load_image(path)
    array = np.asarray(image)
    background = estimate_background(array, preset.background.border_fraction)
    masks = build_masks(array, background, preset.mask, preset.background.border_fraction)
    if not masks.found:
        return None

    angle = angle_mod.classify(masks.solid, masks.bbox, masks.components)
    # фото с маркетплейса могут прийти уменьшенными — приводим к холсту пресета
    scale = preset.canvas.width / image.width

    def margins_of(box) -> dict[str, float]:
        return {
            "top": round(box[1] * scale, 1),
            "bottom": round((image.height - 1 - box[3]) * scale, 1),
            "left": round(box[0] * scale, 1),
            "right": round((image.width - 1 - box[2]) * scale, 1),
        }

    box = masks.bbox
    # устойчивая оценка: на макро-кадрах товар лезет в рамку и портит обычный std
    spread = background_variation(difference_map(array, background),
                                  preset.background.border_fraction)

    return Measurement(
        name=path.name,
        width=image.width,
        height=image.height,
        canvas_matches=image.size == (preset.canvas.width, preset.canvas.height),
        background=tuple(int(c) for c in background),
        background_spread=round(float(spread), 3),
        threshold=masks.threshold,
        angle_kind=angle.kind,
        angle_label=angle.label,
        cropped_sides=masks.cropped_sides,
        margins=margins_of(box),
        soft_margins=margins_of(masks.soft_bbox) if masks.soft_bbox else {},
        fill_width=round((box[2] - box[0] + 1) * scale / preset.zone_width, 4),
        fill_height=round((box[3] - box[1] + 1) * scale / preset.zone_height, 4),
        center_offset=round(((box[0] + box[2] + 1) / 2 * scale) - preset.center_x, 1),
        shadow_px=masks.shadow_px,
        shadow_confirmed=masks.shadow_confirmed,
    )


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    return {"median": round(median(values), 1), "min": round(min(values), 1),
            "max": round(max(values), 1), "count": len(values)}


def summarize(measurements: list[Measurement], preset: Preset) -> dict:
    """Сводка: что эталоны говорят о правилах маркетплейса."""
    fitted = [m for m in measurements if m.fitted]
    summary: dict = {
        "files": len(measurements),
        "fitted": len(fitted),
        "cropped": len(measurements) - len(fitted),
        "canvas_matches": sum(m.canvas_matches for m in measurements),
        "canvas_expected": [preset.canvas.width, preset.canvas.height],
        "backgrounds": sorted({m.background for m in measurements}),
        # только по вписанным: на макро-кадрах товар занимает всю рамку и
        # любая оценка «разброса фона» там измеряет товар, а не фон
        "background_spread": _stats([m.background_spread for m in fitted]),
        "shadows_found": sum(m.shadow_confirmed for m in measurements),
    }
    if fitted:
        for key in ("top", "bottom", "left", "right"):
            summary[f"margin_{key}"] = _stats([m.margins[key] for m in fitted])
        summary["fill_width"] = _stats([m.fill_width for m in fitted])
        summary["fill_height"] = _stats([m.fill_height for m in fitted])
        summary["center_offset"] = _stats([m.center_offset for m in fitted])
        summary["width_limited"] = sum(
            1 for m in fitted if m.fill_width >= m.fill_height
        )
        by_angle: dict[str, dict] = {}
        for kind in {m.angle_kind for m in fitted}:
            rows = [m for m in fitted if m.angle_kind == kind]
            by_angle[kind] = {
                "count": len(rows),
                "fill_width": _stats([m.fill_width for m in rows]),
                "margin_bottom": _stats([m.margins["bottom"] for m in rows]),
            }
        summary["by_angle"] = by_angle
    return summary


def analyze_paths(paths: list[Path], preset: Preset) -> tuple[list[Measurement], dict]:
    measurements: list[Measurement] = []
    for path in sorted(paths):
        if not is_supported(path):
            continue
        measured = measure_file(path, preset)
        if measured is not None:
            measurements.append(measured)
    return measurements, summarize(measurements, preset)


def collect(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return [p for p in sorted(target.rglob("*")) if p.is_file() and is_supported(p)]


def to_json(measurements: list[Measurement], summary: dict) -> str:
    return json.dumps(
        {"summary": summary, "files": [asdict(m) for m in measurements]},
        ensure_ascii=False, indent=2,
    )


def to_markdown(measurements: list[Measurement], summary: dict, preset: Preset) -> str:
    lines = [f"# Замер эталонов — {preset.name}", ""]
    lines.append(f"Файлов: **{summary['files']}**, вписанных: **{summary['fitted']}**, "
                 f"макро/обрезанных: **{summary['cropped']}**.")
    lines.append(f"Совпал холст {summary['canvas_expected'][0]}×{summary['canvas_expected'][1]}: "
                 f"**{summary['canvas_matches']}** из {summary['files']}.")
    spread = summary.get("background_spread") or {}
    lines.append(f"Цвета фона: {', '.join(str(b) for b in summary['backgrounds'])}; "
                 f"разброс по рамке у вписанных кадров: медиана {spread.get('median', '—')}, "
                 f"максимум {spread.get('max', '—')}.")
    lines.append(f"Кадров с распознанной тенью: **{summary['shadows_found']}**.")
    lines.append("")
    if summary.get("margin_bottom"):
        lines += ["## Правила, вычитанные из эталонов", "",
                  "| Параметр | Медиана | Мин | Макс |", "|---|---|---|---|"]
        titles = {"margin_top": "Отступ сверху", "margin_bottom": "Отступ снизу",
                  "margin_left": "Отступ слева", "margin_right": "Отступ справа",
                  "fill_width": "Заполнение ширины зоны", "fill_height": "Заполнение высоты зоны",
                  "center_offset": "Сдвиг центра по X"}
        for key, title in titles.items():
            stats = summary.get(key)
            if stats:
                lines.append(f"| {title} | {stats['median']} | {stats['min']} | {stats['max']} |")
        lines.append("")
        lines.append(f"Ограничителем масштаба была ширина у "
                     f"**{summary['width_limited']}** из {summary['fitted']} вписанных кадров.")
        lines.append("")
        lines += ["## По ракурсам", "", "| Ракурс | Кадров | Заполнение ширины | Отступ снизу |",
                  "|---|---|---|---|"]
        for kind, data in sorted(summary.get("by_angle", {}).items()):
            lines.append(f"| {angle_mod.LABELS.get(kind, kind)} | {data['count']} | "
                         f"{data['fill_width']['median']} | {data['margin_bottom']['median']} |")
        lines.append("")
    lines += ["## Файлы", "",
              "| Файл | Ракурс | Низ | Верх | Слева | Справа | Ширина зоны | Статус |",
              "|---|---|---|---|---|---|---|---|"]
    for m in measurements:
        status = "вписан" if m.fitted else "обрезан: " + ", ".join(m.cropped_sides)
        lines.append(
            f"| {m.name} | {m.angle_label} | {m.margins['bottom']:.0f} | {m.margins['top']:.0f} | "
            f"{m.margins['left']:.0f} | {m.margins['right']:.0f} | {m.fill_width:.3f} | {status} |")
    return "\n".join(lines) + "\n"
