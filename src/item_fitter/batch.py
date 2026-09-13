"""Пакетный прогон по папке."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from . import matting as matmod
from .config import Settings
from .pipeline import ProcessResult, process_file

__all__ = ["find_images", "run_batch", "SUPPORTED_SUFFIXES"]

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


def find_images(src: str | Path, recursive: bool = True) -> list[Path]:
    """Собирает файлы изображений. Файл на входе допустим наравне с папкой."""
    src = Path(src)
    if src.is_file():
        return [src] if src.suffix.lower() in SUPPORTED_SUFFIXES else []
    if not src.is_dir():
        raise FileNotFoundError(f"Не найдено: {src}")
    it: Iterable[Path] = src.rglob("*") if recursive else src.glob("*")
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)


def run_batch(
    src: str | Path,
    out_dir: str | Path,
    settings: Settings,
    recursive: bool = True,
    progress: Callable[[int, int, Path, ProcessResult | None, Exception | None], None] | None = None,
) -> list[ProcessResult]:
    """Обрабатывает все кадры и складывает результат в out_dir.

    Сессия матирования создаётся один раз на весь пакет: инициализация нейросети
    занимает секунды, и делать её на каждом кадре — значит утроить время прогона.

    Ошибка на одном кадре не роняет весь пакет: битый файл пропускается и попадает
    в отчёт как FAIL. На потоке в 350 кадров это принципиально.
    """
    src, out_dir = Path(src), Path(out_dir)
    files = find_images(src, recursive)
    out_dir.mkdir(parents=True, exist_ok=True)

    matte_fn = matting_fn = matmod.get_backend(settings.matting)
    root = src if src.is_dir() else src.parent
    results: list[ProcessResult] = []

    for i, path in enumerate(files, start=1):
        rel = path.relative_to(root) if path.is_relative_to(root) else Path(path.name)
        dst = out_dir / rel.with_suffix(".jpg")
        try:
            res = process_file(path, dst, settings, matte_fn=matting_fn)
            results.append(res)
            if progress:
                progress(i, len(files), path, res, None)
        except Exception as exc:  # noqa: BLE001 — падение одного кадра не должно рушить пакет
            if progress:
                progress(i, len(files), path, None, exc)

    return results
