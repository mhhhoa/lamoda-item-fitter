"""Фоновая обработка пакета без блокировки окна."""

from __future__ import annotations

import threading
from typing import Sequence

from PySide6.QtCore import QObject, Signal, Slot

from ..batch import Job, Outcome, process, summarize
from ..config import Preset


class BatchWorker(QObject):
    """Гоняет план в пуле потоков и докладывает о каждом файле."""

    progressed = Signal(int, int)
    produced = Signal(object)
    completed = Signal(dict)

    def __init__(self, jobs: Sequence[Job], preset: Preset, workers: int = 4) -> None:
        super().__init__()
        self._jobs = list(jobs)
        self._preset = preset
        self._workers = workers
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @Slot()
    def run(self) -> None:
        total = len(self._jobs)
        done = 0
        lock = threading.Lock()

        def on_result(outcome: Outcome) -> None:
            nonlocal done
            with lock:
                done += 1
                current = done
            self.produced.emit(outcome)
            self.progressed.emit(current, total)

        outcomes = process(self._jobs, self._preset, on_result=on_result,
                           cancel=self._cancel, workers=self._workers)
        self.completed.emit(summarize(outcomes))
