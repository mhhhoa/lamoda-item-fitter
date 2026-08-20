"""Задания, которые намеренно убивают рабочий процесс.

Нужны, чтобы проверить главное обещание программы: падение обработки не
уносит окно и не останавливает очередь. Функции лежат в отдельном модуле,
потому что рабочий процесс импортирует их по имени.
"""

from __future__ import annotations

import ctypes
import os

from lamoda_item_fitter.batch import Outcome, process_one
from lamoda_item_fitter.config import Preset
from lamoda_item_fitter.fitter import FITTED
from lamoda_item_fitter.batch import Job

#: файл с этим фрагментом в имени валит процесс
POISON = "яд"


def exit_task(job: Job, preset: Preset) -> Outcome:
    """Убивает процесс без единого шанса перехватить — как сбой в библиотеке."""
    if POISON in job.source.name:
        os._exit(1)
    return process_one(job, preset)


def segfault_task(job: Job, preset: Preset) -> Outcome:
    """Настоящий сегфолт: обращение по нулевому адресу."""
    if POISON in job.source.name:
        ctypes.string_at(0)
    return process_one(job, preset)


def ok_task(job: Job, preset: Preset) -> Outcome:
    return process_one(job, preset)


def raise_task(job: Job, preset: Preset) -> Outcome:
    """Обычное исключение внутри задания — его обязан поймать сам обработчик."""
    if POISON in job.source.name:
        raise RuntimeError("сломанный кадр")
    return process_one(job, preset)
