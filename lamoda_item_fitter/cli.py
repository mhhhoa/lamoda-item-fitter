"""Командная строка: подгонка и калибровка без интерфейса."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyze import analyze_paths, collect, to_json, to_markdown
from .batch import (
    COPY, FAILED, OVERWRITE, SKIP, apply_policy, conflicts, inspect_one, plan,
    process_one, summarize,
)
from .runner import run_isolated
from .config import Preset
from .fitter import FITTED, PASSTHROUGH, SKIPPED
from .downloads import downloads_dir

STATUS_LABELS = {
    FITTED: "подогнан",
    PASSTHROUGH: "перенесён",
    SKIPPED: "пропущен",
    FAILED: "ошибка",
}


def _preset(args: argparse.Namespace) -> Preset:
    preset = Preset.load(args.preset) if args.preset else Preset.load()
    output = preset.output
    if getattr(args, "format", None):
        output = output.__class__(**{**output.__dict__, "format": args.format})
    if getattr(args, "quality", None):
        output = output.__class__(**{**output.__dict__, "jpeg_quality": args.quality})
    return preset.replace(output=output)


def command_fit(args: argparse.Namespace) -> int:
    preset = _preset(args)
    jobs = plan([Path(p) for p in args.paths], preset,
                output_root=Path(args.out) if args.out else None)
    if not jobs:
        print("Не нашлось ни одного изображения.", file=sys.stderr)
        return 1

    clashing = conflicts(jobs)
    if clashing:
        print(f"В папке назначения уже есть {len(clashing)} файлов с такими именами — "
              f"политика: {args.on_conflict}")
    jobs, skipped = apply_policy(jobs, args.on_conflict)
    for job in skipped:
        print(f"  пропущен (уже есть): {job.title}")

    total = len(jobs)
    done = 0

    def report(outcome):
        nonlocal done
        done += 1
        label = STATUS_LABELS.get(outcome.status, outcome.status)
        line = f"[{done}/{total}] {label}: {outcome.job.title}"
        if outcome.status == FITTED:
            margins = outcome.metrics.margins
            line += (f" — низ {margins.get('bottom')}, поля "
                     f"{margins.get('left')}/{margins.get('right')}, "
                     f"{outcome.metrics.angle_label}, {outcome.size_bytes / 1048576:.2f} МБ")
        if outcome.reason:
            line += f" — {outcome.reason}"
        print(line)
        for warning in outcome.warnings:
            print(f"        ! {warning}")

    task = inspect_one if getattr(args, "analyze_only", False) else process_one
    outcomes = run_isolated(jobs, preset, task, on_result=report, workers=args.workers)
    counts = summarize(outcomes)
    print(f"\nГотово: подогнано {counts[FITTED]}, перенесено {counts[PASSTHROUGH]}, "
          f"пропущено {counts[SKIPPED]}, ошибок {counts[FAILED]}.")
    destination = Path(args.out) if args.out else downloads_dir()
    print(f"Папка результата: {destination}")
    return 1 if counts[FAILED] else 0


def command_analyze(args: argparse.Namespace) -> int:
    preset = _preset(args)
    paths = collect(Path(args.path))
    if not paths:
        print("Не нашлось ни одного изображения.", file=sys.stderr)
        return 1
    measurements, summary = analyze_paths(paths, preset)
    markdown = to_markdown(measurements, summary, preset)
    if args.md:
        Path(args.md).write_text(markdown, encoding="utf-8")
        print(f"Отчёт: {args.md}")
    else:
        print(markdown)
    if args.json:
        Path(args.json).write_text(to_json(measurements, summary), encoding="utf-8")
        print(f"Данные: {args.json}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lamoda_item_fitter",
        description="Подгонка предметных фото под правила маркетплейса Ламода.",
    )
    parser.add_argument("--preset", help="файл пресета вместо встроенного")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fit = subparsers.add_parser("fit", help="подогнать файлы или папки")
    fit.add_argument("paths", nargs="+", help="файлы и папки с исходниками")
    fit.add_argument("--out", help="папка результата (по умолчанию «Загрузки»)")
    fit.add_argument("--format", choices=["jpeg", "png"], help="формат сохранения")
    fit.add_argument("--quality", type=int, help="качество JPEG")
    fit.add_argument("--on-conflict", choices=[COPY, OVERWRITE, SKIP], default=COPY,
                     help="что делать, если файл с таким именем уже есть")
    fit.add_argument("--workers", type=int, help="сколько файлов обрабатывать разом")
    fit.add_argument("--analyze-only", action="store_true",
                     help="только распознать кадры, ничего не сохраняя")
    fit.set_defaults(func=command_fit)

    analyze = subparsers.add_parser(
        "analyze", help="замерить уже опубликованные фото и выверить пресет")
    analyze.add_argument("path", help="файл или папка с эталонами")
    analyze.add_argument("--json", help="куда сохранить данные замера")
    analyze.add_argument("--md", help="куда сохранить отчёт")
    analyze.set_defaults(func=command_analyze)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
