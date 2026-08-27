"""Пакетная обработка: куда что сохранять и как это выполнить."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from . import errors
from .config import Preset
from .downloads import downloads_dir
from .fitter import (
    FITTED, PASSTHROUGH, SKIPPED, UNRECOGNIZED, FitMetrics, fit_image, inspect_image,
)
from .imageio import UnreadableImage, is_supported, load_image, output_suffix, save_image

OVERWRITE = "overwrite"
COPY = "copy"
SKIP = "skip"

FAILED = "failed"
CONFLICT = "conflict"


@dataclass
class Job:
    """Один файл на обработку и его будущее место в папке результата."""

    source: Path
    destination: Path
    #: путь внутри папки результата — для отображения в интерфейсе
    relative: Path

    @property
    def title(self) -> str:
        return str(self.relative)


@dataclass
class Outcome:
    job: Job
    status: str
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    metrics: FitMetrics = field(default_factory=FitMetrics)
    size_bytes: int = 0
    quality: int = 0

    @property
    def written(self) -> bool:
        return self.status in (FITTED, PASSTHROUGH)


def _unique(path: Path, taken: set[Path]) -> Path:
    """Свободное имя вида «файл (2).jpg» — молча ничего не затираем."""
    candidate = path
    index = 2
    while candidate in taken or candidate.exists():
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        index += 1
    return candidate


def collect_inputs(paths: Iterable[Path]) -> tuple[list[Path], list[Path]]:
    """Делит выбранное на отдельные файлы и папки."""
    files: list[Path] = []
    folders: list[Path] = []
    for path in paths:
        path = Path(path)
        if path.is_dir():
            folders.append(path)
        elif path.is_file() and is_supported(path):
            files.append(path)
    return files, folders


def plan(paths: Sequence[Path], preset: Preset, output_root: Path | None = None) -> list[Job]:
    """Строит план сохранения.

    Выбрали файлы — результат ложится прямо в «Загрузки». Выбрали папку —
    рядом появляется папка с тем же именем, со всей вложенностью внутри.
    Имя каждого файла получает суффикс из пресета.
    """
    root = Path(output_root) if output_root else downloads_dir()
    suffix = preset.output.suffix
    extension = output_suffix(preset.output)
    files, folders = collect_inputs(paths)

    jobs: list[Job] = []
    for source in files:
        name = f"{source.stem}{suffix}{extension}"
        jobs.append(Job(source, root / name, Path(name)))

    for folder in folders:
        folder_name = f"{folder.name}{suffix}" if preset.output.suffix_on_folder else folder.name
        for source in sorted(folder.rglob("*")):
            if not source.is_file() or not is_supported(source):
                continue
            inner = source.relative_to(folder).parent
            name = f"{source.stem}{suffix}{extension}"
            relative = Path(folder_name) / inner / name
            jobs.append(Job(source, root / relative, relative))
    return jobs


def conflicts(jobs: Sequence[Job]) -> list[Job]:
    """Задания, чей файл уже лежит в папке назначения."""
    return [job for job in jobs if job.destination.exists()]


def apply_policy(jobs: Sequence[Job], policy: str) -> tuple[list[Job], list[Job]]:
    """Разводит план по выбранной политике конфликтов.

    Итоговые имена раздаются здесь, в один поток: иначе два воркера могли бы
    выбрать одно и то же свободное имя.
    """
    taken: set[Path] = set()
    accepted: list[Job] = []
    skipped: list[Job] = []
    for job in jobs:
        exists = job.destination.exists()
        if exists and policy == SKIP:
            skipped.append(job)
            continue
        destination = job.destination
        if policy == COPY or destination in taken:
            destination = _unique(destination, taken)
        taken.add(destination)
        accepted.append(Job(job.source, destination, job.relative))
    return accepted, skipped


def process_one(job: Job, preset: Preset) -> Outcome:
    """Обрабатывает и сохраняет один файл.

    Ни один исходник не имеет права уронить пакет, поэтому ловится всё, кроме
    отмены пользователем: сбой одного файла превращается в статус его строки,
    а остальные продолжают обрабатываться.
    """
    try:
        image = load_image(job.source)
    except (KeyboardInterrupt, SystemExit):
        raise
    except UnreadableImage as error:
        errors.log_only(f"чтение {job.source.name}", error)
        return Outcome(job, FAILED, reason=str(error))
    except BaseException as error:  # noqa: BLE001 — сбой файла не должен ронять пакет
        errors.log_only(f"чтение {job.source.name}", error)
        return Outcome(job, FAILED, reason=f"не удалось открыть файл — {errors.describe(error)}")

    try:
        result = fit_image(image, preset)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as error:  # noqa: BLE001
        errors.log_only(f"обработка {job.source.name}", error)
        return Outcome(job, FAILED, reason=f"ошибка обработки — {errors.describe(error)}")

    if not result.ok or result.image is None:
        return Outcome(job, result.status, reason=result.reason,
                       warnings=result.warnings, metrics=result.metrics)

    try:
        size, quality = save_image(result.image, job.destination, preset.output)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as error:  # noqa: BLE001
        errors.log_only(f"сохранение {job.destination.name}", error)
        return Outcome(job, FAILED, reason=f"не удалось сохранить — {errors.describe(error)}",
                       warnings=result.warnings, metrics=result.metrics)

    warnings = list(result.warnings)
    if size > preset.output.max_bytes:
        warnings.append(f"файл {size / 1048576:.1f} МБ — больше лимита "
                        f"{preset.output.max_bytes / 1048576:.0f} МБ")
    elif quality and quality < preset.output.jpeg_quality:
        warnings.append(f"качество снижено до {quality}, чтобы уложиться в лимит веса")

    return Outcome(job, result.status, reason=result.reason, warnings=warnings,
                   metrics=result.metrics, size_bytes=size, quality=quality)


def inspect_one(job: Job, preset: Preset) -> Outcome:
    """Быстрое распознавание без подгонки и без записи — для кнопки «Анализ»."""
    try:
        # распознавание идёт по уменьшенной копии, поэтому и читать кадр
        # в полном разрешении незачем — это экономит сотни мегабайт
        image = load_image(job.source, max_side=preset.analysis_max_side)
    except UnreadableImage as error:
        errors.log_only(f"чтение {job.source.name}", error)
        return Outcome(job, FAILED, reason=str(error))
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as error:  # noqa: BLE001
        errors.log_only(f"чтение {job.source.name}", error)
        return Outcome(job, FAILED, reason=f"не удалось открыть файл — {errors.describe(error)}")

    try:
        verdict = inspect_image(image, preset)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as error:  # noqa: BLE001
        errors.log_only(f"анализ {job.source.name}", error)
        return Outcome(job, FAILED, reason=f"ошибка анализа — {errors.describe(error)}")

    return Outcome(job, verdict.status, reason=verdict.reason,
                   warnings=verdict.warnings, metrics=verdict.metrics)


def summarize(outcomes: Sequence[Outcome]) -> dict[str, int]:
    counts = {FITTED: 0, PASSTHROUGH: 0, SKIPPED: 0, UNRECOGNIZED: 0, FAILED: 0}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    return counts
