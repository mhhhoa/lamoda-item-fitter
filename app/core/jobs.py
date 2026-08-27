"""Сбор файлов из папок и раскладка результатов по местам."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from .settings import CONFLICT_OVERWRITE, CONFLICT_SKIP, INPUT_EXTENSIONS, Settings


@dataclass(frozen=True)
class Job:
    """Одна картинка в очереди.

    `root` — папка, относительно которой считается путь при сохранении
    структуры. Для файла, добавленного поштучно, это его же папка, так что
    он ложится в корень выгрузки.
    """

    source: Path
    root: Path

    @property
    def relative(self) -> Path:
        try:
            return self.source.relative_to(self.root)
        except ValueError:
            return Path(self.source.name)

    @property
    def folder_label(self) -> str:
        parent = self.relative.parent
        return "" if parent == Path(".") else parent.as_posix()


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in INPUT_EXTENSIONS


def collect(paths: list[Path]) -> list[Job]:
    """Разворачивает список файлов и папок в плоский список задач.

    Папка попадает в результат вместе со своим именем: перетащив
    `Товары/Платье синее`, вы получите на выходе такую же папку.
    """
    jobs: list[Job] = []
    seen: set[Path] = set()

    for path in paths:
        try:
            path = path.expanduser()
            if path.is_file():
                candidates = [(path, path.parent)]
            elif path.is_dir():
                candidates = [
                    (child, path.parent)
                    for child in sorted(path.rglob("*"))
                    if child.is_file()
                ]
            else:
                continue
        except OSError:
            continue

        for source, root in candidates:
            if not is_supported(source):
                continue
            try:
                key = source.resolve()
            except OSError:
                key = source
            if key in seen:
                continue
            seen.add(key)
            jobs.append(Job(source, root))

    return jobs


class DestinationPlanner:
    """Выдаёт итоговые пути, следя за тем, чтобы они не сталкивались.

    Резервирование потокобезопасно: обработка идёт в несколько потоков, и
    два файла с одинаковым именем из разных папок не должны драться за
    одну и ту же строчку на диске.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._taken: set[str] = set()
        self._lock = threading.Lock()

    def reserve(self, job: Job, extension: str) -> Path | None:
        """Возвращает свободный путь под результат либо None, если пропускаем."""
        base_dir = Path(self._settings.output_dir)
        if self._settings.keep_structure:
            base_dir = base_dir / job.relative.parent

        stem = job.source.stem + self._settings.name_suffix
        with self._lock:
            candidate = base_dir / f"{stem}{extension}"
            if self._is_free(candidate, job):
                self._taken.add(self._key(candidate))
                return candidate

            if self._settings.on_conflict == CONFLICT_SKIP:
                return None
            # «Перезаписать» относится к тому, что лежало на диске до запуска.
            # Затирать результат, записанный этим же прогоном пару секунд
            # назад, — это потерять файл, а не перезаписать старый.
            if (
                self._settings.on_conflict == CONFLICT_OVERWRITE
                and self._key(candidate) not in self._taken
                and not self._same_file(candidate, job.source)
            ):
                self._taken.add(self._key(candidate))
                return candidate

            for index in range(1, 1000):
                candidate = base_dir / f"{stem}_{index}{extension}"
                if self._is_free(candidate, job):
                    self._taken.add(self._key(candidate))
                    return candidate
        return None

    # --- внутреннее ------------------------------------------------------
    @staticmethod
    def _key(path: Path) -> str:
        return str(path).lower()

    def _is_free(self, candidate: Path, job: Job) -> bool:
        if self._key(candidate) in self._taken:
            return False
        # Записать результат поверх исходника — верный способ потерять
        # оригиналы, поэтому такой путь считаем занятым всегда.
        if self._same_file(candidate, job.source):
            return False
        return not candidate.exists()

    @staticmethod
    def _same_file(a: Path, b: Path) -> bool:
        try:
            return a.resolve() == b.resolve()
        except OSError:
            return str(a).lower() == str(b).lower()
