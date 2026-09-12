"""Командный интерфейс.

Основной сценарий одной строкой:
    fitter run ./in -o ./out
"""

from __future__ import annotations

from pathlib import Path

import typer

from . import report as repmod
from .batch import find_images, run_batch
from .config import Settings, list_presets, load_preset
from .qa import CHECK, FAIL, OK

app = typer.Typer(
    add_completion=False,
    help="Пакетная замена студийного фона на белый под стандарты маркетплейсов.",
)

_MARK = {OK: "[ ok ]", CHECK: "[ !! ]", FAIL: "[FAIL]"}


def _settings(preset: str, **overrides) -> Settings:
    base = load_preset(preset)
    return base.replace(**overrides)


@app.command("presets")
def cmd_presets() -> None:
    """Показать доступные пресеты."""
    for name in list_presets():
        s = load_preset(name)
        typer.echo(
            f"  {name:<20} матирование={s.matting:<8} фон={s.target_bg} "
            f"геометрия={s.geometry_mode} wb={s.wb_strength}"
        )


@app.command("run")
def cmd_run(
    src: Path = typer.Argument(..., help="Папка или файл с исходниками."),
    out: Path = typer.Option(Path("out"), "--out", "-o", help="Куда складывать результат."),
    preset: str = typer.Option("lamoda", "--preset", "-p", help="Имя пресета или путь к YAML."),
    matting: str = typer.Option(None, "--matting", help="Переопределить бэкенд матирования."),
    wb: float = typer.Option(None, "--wb", help="Сила снятия цветного рефлекса, 0..1."),
    reflection: float = typer.Option(None, "--reflection", help="Сила отражения, 0..1."),
    report: Path = typer.Option(None, "--report", help="Путь к HTML-отчёту."),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive"),
) -> None:
    """Обработать папку: заменить фон на белый и выгрузить готовые JPEG."""
    settings = _settings(preset, matting=matting, wb_strength=wb, reflection_strength=reflection)
    files = find_images(src, recursive)
    if not files:
        typer.secho(f"В {src} не найдено изображений.", fg="red")
        raise typer.Exit(1)

    typer.echo(f"Кадров: {len(files)} · пресет: {preset} · матирование: {settings.matting}")
    failures: list[tuple[Path, Exception]] = []

    def on_progress(i, total, path, res, exc):
        if exc is not None:
            failures.append((path, exc))
            typer.secho(f"[{i}/{total}] [FAIL] {path.name}: {exc}", fg="red")
            return
        colour = {OK: "green", CHECK: "yellow", FAIL: "red"}[res.verdict]
        typer.secho(
            f"[{i}/{total}] {_MARK[res.verdict]} {path.name}  "
            f"углы={res.report.metrics.get('bg_corner_min')} "
            f"ΔE={res.report.metrics.get('product_delta_e')} "
            f"({res.timing['total']:.1f}s)",
            fg=colour,
        )

    results = run_batch(src, out, settings, recursive=recursive, progress=on_progress)

    tally = {v: sum(1 for r in results if r.verdict == v) for v in (OK, CHECK, FAIL)}
    typer.echo("")
    typer.secho(f"Готово без замечаний: {tally[OK]}", fg="green")
    typer.secho(f"Проверить глазами:    {tally[CHECK]}", fg="yellow")
    typer.secho(f"Ошибки:               {tally[FAIL] + len(failures)}", fg="red")

    report_path = report or Path(out) / "_отчёт.html"
    repmod.write_report(report_path, results, failures, preset_name=preset)
    typer.echo(f"\nОтчёт: {report_path}")


@app.command("compare")
def cmd_compare(
    folder: Path = typer.Argument(..., help="Папка с парами «артикул_before» / «артикул_after»."),
    preset: str = typer.Option("lamoda", "--preset", "-p"),
    report: Path = typer.Option(Path("сверка.html"), "--report"),
) -> None:
    """Сверить свою обработку с эталонами подрядчика."""
    from .compare import compare_folder

    settings = load_preset(preset)
    scores = compare_folder(folder, settings)
    for s in sorted(scores, key=lambda x: -x.delta_e_mean):
        typer.echo(
            f"  {s.name:<24} ΔE={s.delta_e_mean:<6} товар={s.delta_e_product:<6} "
            f"фон={s.delta_e_background:<6} SSIM={s.ssim}  {s.verdict}"
        )
    mean = sum(s.delta_e_mean for s in scores) / len(scores)
    typer.secho(f"\nСреднее расхождение: ΔE2000 = {mean:.2f}", bold=True)
    repmod.write_compare_report(report, scores, preset_name=preset)
    typer.echo(f"Отчёт: {report}")


@app.command("calibrate")
def cmd_calibrate(
    folder: Path = typer.Argument(..., help="Папка с эталонными парами."),
    preset: str = typer.Option("lamoda", "--preset", "-p"),
    save: Path = typer.Option(None, "--save", help="Куда записать подобранный пресет (YAML)."),
) -> None:
    """Подобрать параметры так, чтобы результат сошёлся с эталонами подрядчика."""
    import yaml

    from .compare import calibrate

    base = load_preset(preset)

    def on_progress(i, total, params, score):
        typer.echo(f"  [{i}/{total}] {params} -> ΔE {score}")

    best, scored = calibrate(folder, base, progress=on_progress)
    typer.echo("")
    typer.secho("Лучшие параметры:", bold=True)
    for k, v in scored[0][0].items():
        typer.echo(f"  {k}: {v}")
    typer.secho(f"Среднее расхождение: ΔE2000 = {scored[0][1]}", bold=True)

    if save:
        Path(save).write_text(
            yaml.safe_dump(best.to_dict(), allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        typer.echo(f"Пресет сохранён: {save}")


@app.command("ui")
def cmd_ui(
    host: str = typer.Option("127.0.0.1", "--host", help="0.0.0.0 — открыть доступ коллегам по сети."),
    port: int = typer.Option(
        None, "--port", help="По умолчанию подбирается свободный, начиная с 7860."
    ),
    share: bool = typer.Option(False, "--share", help="Временная публичная ссылка."),
) -> None:
    """Открыть визуальный интерфейс в браузере."""
    from .app import launch

    launch(host=host, port=port, share=share)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
