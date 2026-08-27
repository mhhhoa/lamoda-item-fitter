"""Запуск обработки в несколько потоков и связь с интерфейсом."""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .core.compressor import Cancelled, Result, Status, compress_file
from .core.jobs import DestinationPlanner, Job
from .core.settings import Settings


@dataclass
class Summary:
    total: int = 0
    processed: int = 0
    errors: int = 0
    too_big: int = 0
    skipped: int = 0
    source_bytes: int = 0
    output_bytes: int = 0
    cancelled: bool = False

    def add(self, result: Result) -> None:
        self.processed += 1
        if result.status is Status.ERROR:
            self.errors += 1
        elif result.status is Status.TOO_BIG:
            self.too_big += 1
        elif result.status is Status.SKIPPED:
            self.skipped += 1
        if result.status is not Status.SKIPPED:
            self.source_bytes += result.source_size
            self.output_bytes += result.output_size


class _TaskSignals(QObject):
    done = Signal(int, object)


class _Task(QRunnable):
    """Обработка одного файла в отдельном потоке пула."""

    def __init__(
        self,
        index: int,
        job: Job,
        planner: DestinationPlanner,
        settings: Settings,
        cancel: threading.Event,
        signals: _TaskSignals,
    ):
        super().__init__()
        self.index = index
        self.job = job
        self.planner = planner
        self.settings = settings
        self.cancel = cancel
        self.signals = signals

    def run(self) -> None:  # noqa: D102
        def check_cancel() -> None:
            if self.cancel.is_set():
                raise Cancelled

        try:
            check_cancel()
            result = compress_file(
                self.job.source,
                lambda extension: self.planner.reserve(self.job, extension),
                self.settings,
                check_cancel,
            )
        except Cancelled:
            result = Result(Status.SKIPPED, self.job.source, message="Отменено")
        except MemoryError:
            result = Result(
                Status.ERROR, self.job.source,
                message="Не хватило памяти — попробуйте меньше потоков в настройках",
            )
        except Exception as error:  # noqa: BLE001 - падать всей очередью нельзя
            traceback.print_exc()
            result = Result(Status.ERROR, self.job.source, message=_readable(error))
        self.signals.done.emit(self.index, result)


def _readable(error: Exception) -> str:
    """Переводит внутренние формулировки библиотек в человеческие."""
    text = str(error).strip() or error.__class__.__name__
    if "cannot identify image file" in text:
        return "Не похоже на картинку — файл повреждён или не тот формат"
    if "Truncated File Read" in text or "image file is truncated" in text:
        return "Файл обрывается на середине — скопировался не полностью?"
    if "broken data stream" in text:
        return "Не удалось записать результат — попробуйте другой формат вывода"
    if isinstance(error, (PermissionError,)):
        return "Нет доступа к файлу — закройте его в других программах"
    if isinstance(error, FileNotFoundError):
        return "Файл исчез с диска"
    if isinstance(error, OSError) and "No space" in text:
        return "На диске закончилось место"
    return text


class Pipeline(QObject):
    """Гоняет очередь задач через пул потоков и отчитывается наружу."""

    item_done = Signal(int, object)   # индекс строки, Result
    progress = Signal(int, int)       # сделано, всего
    finished = Signal(object)         # Summary

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._cancel = threading.Event()
        self._signals = _TaskSignals()
        self._signals.done.connect(self._on_task_done)
        self._summary = Summary()
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self, jobs: list[Job], settings: Settings) -> None:
        if self._running or not jobs:
            return
        self._cancel.clear()
        self._summary = Summary(total=len(jobs))
        self._running = True
        self._pool.setMaxThreadCount(settings.effective_threads)
        planner = DestinationPlanner(settings)
        for index, job in enumerate(jobs):
            self._pool.start(_Task(index, job, planner, settings, self._cancel, self._signals))
        self.progress.emit(0, len(jobs))

    def cancel(self) -> None:
        if self._running:
            self._cancel.set()

    def wait(self, milliseconds: int = 15000) -> bool:
        """Дожидается остановки задач — иначе они эмитят сигналы в мёртвое окно.

        Пустой пул означает, что работы больше нет, даже если отчёты о
        последних задачах ещё не разобраны циклом событий.
        """
        done = self._pool.waitForDone(milliseconds)
        if done:
            self._running = False
        else:
            # Не дождались: отцепляем сигналы, чтобы опоздавшая задача не
            # выстрелила в уже разрушенное окно.
            try:
                self._signals.done.disconnect()
            except RuntimeError:
                pass
        return done

    def _on_task_done(self, index: int, result: Result) -> None:
        self._summary.add(result)
        self.item_done.emit(index, result)
        self.progress.emit(self._summary.processed, self._summary.total)
        if self._summary.processed >= self._summary.total:
            self._running = False
            self._summary.cancelled = self._cancel.is_set()
            self.finished.emit(self._summary)
