"""Фоновая обработка пакета без блокировки окна."""

from __future__ import annotations

import threading
from typing import Sequence

from PySide6.QtCore import QObject, Signal, Slot

from .. import errors
from ..batch import FAILED, Job, Outcome, inspect_one, process_one, summarize
from ..config import Preset
from ..runner import run_isolated


class BatchWorker(QObject):
    """Гоняет план в пуле потоков и докладывает о каждом файле."""

    progressed = Signal(int, int)
    produced = Signal(object)
    completed = Signal(dict)

    def __init__(self, jobs: Sequence[Job], preset: Preset,
                 analyze_only: bool = False, workers: int | None = None) -> None:
        super().__init__()
        self._jobs = list(jobs)
        self._preset = preset
        self._analyze_only = analyze_only
        self._workers = workers
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @Slot()
    def run(self) -> None:
        """Точка входа фонового потока.

        Тело целиком под защитой: исключение, вылетевшее из слота, PySide6
        трактует как фатальное и закрывает приложение без единого сообщения.
        Что бы ни случилось, сигнал о завершении обязан прийти — иначе окно
        навсегда останется в состоянии «идёт обработка».
        """
        counts: dict = {}
        try:
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

            task = inspect_one if self._analyze_only else process_one
            outcomes = run_isolated(self._jobs, self._preset, task, on_result=on_result,
                                    cancel=self._cancel, workers=self._workers)
            counts = summarize(outcomes)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as error:  # noqa: BLE001 — последний рубеж перед Qt
            errors.report("пакетная обработка", error)
            counts = {FAILED: len(self._jobs)}
        finally:
            try:
                self.completed.emit(counts)
            except Exception:
                pass
