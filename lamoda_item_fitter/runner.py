"""Обработка в отдельных процессах.

Падение внутри системной библиотеки обработки изображений поймать из Python
невозможно: процесс умирает целиком. Пока вся работа шла потоками в одном
процессе, такой сбой уносил и окно, и всю очередь. Поэтому файлы считаются в
отдельных процессах — гибнет только рабочий процесс.

Когда пул ломается, неизвестно, какой именно файл его уронил: вместе с ним
отваливаются все, кто был в работе. Поэтому оставшиеся догоняются по одному —
так виновник вычисляется точно, получает статус и не мешает остальным.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
from typing import Callable, Sequence

from . import errors
from .batch import FAILED, Job, Outcome
from .config import Preset

CRASH_REASON = ("обработка этого файла аварийно завершилась — "
                "он пропущен, остальные обработаны")

#: сколько раз подряд можно пересоздавать упавший пул, прежде чем сдаться и
#: доделать оставшееся в текущем процессе. Без потолка системная проблема
#: (например, недоступность быстрого создания процессов) превращала бы
#: каждый следующий файл в ещё одну попытку поднять пул — и тем медленнее и
#: тяжелее становилась работа, чем больше файлов оставалось
MAX_POOL_RESTARTS = 4


def _run_here(
    jobs: Sequence[Job],
    preset: Preset,
    task: Callable[[Job, Preset], Outcome],
    record: Callable[[Outcome], None],
    cancel: threading.Event | None,
) -> None:
    """Запасной путь: обработка в текущем процессе, по одному файлу.

    Нужен, если отдельные процессы в этой среде вообще не запускаются —
    так бывает, когда защитное ПО не даёт программе порождать копии себя.
    Изоляции здесь нет, но работать программа обязана в любом случае.
    """
    for job in jobs:
        if cancel is not None and cancel.is_set():
            return
        try:
            record(task(job, preset))
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as error:  # noqa: BLE001
            errors.log_only(f"задание {job.title}", error)
            record(Outcome(job, FAILED, reason=f"сбой — {errors.describe(error)}"))


def default_workers() -> int:
    return min(3, max(1, (os.cpu_count() or 2) - 1))


def run_isolated(
    jobs: Sequence[Job],
    preset: Preset,
    task: Callable[[Job, Preset], Outcome],
    on_result: Callable[[Outcome], None] | None = None,
    cancel: threading.Event | None = None,
    workers: int | None = None,
) -> list[Outcome]:
    """Прогоняет задания в рабочих процессах, переживая их падение."""
    outcomes: list[Outcome] = []
    if not jobs:
        return outcomes
    parallel = workers or default_workers()

    def record(outcome: Outcome) -> None:
        outcomes.append(outcome)
        if on_result is not None:
            try:
                on_result(outcome)
            except Exception as error:  # noqa: BLE001
                errors.report("уведомление о результате", error)

    pending = list(jobs)
    context = get_context("spawn")
    processes_work = False
    restarts = 0
    while pending:
        if cancel is not None and cancel.is_set():
            break
        batch = pending
        finished: set[int] = set()
        crashed = False
        try:
            with ProcessPoolExecutor(max_workers=parallel, mp_context=context) as pool:
                futures = {pool.submit(task, job, preset): index
                           for index, job in enumerate(batch)}
                for future in as_completed(futures):
                    index = futures[future]
                    try:
                        record(future.result())
                        finished.add(index)
                        processes_work = True
                    except BrokenProcessPool:
                        crashed = True
                        break
                    except (KeyboardInterrupt, SystemExit):
                        raise
                    except BaseException as error:  # noqa: BLE001
                        errors.log_only(f"задание {batch[index].title}", error)
                        record(Outcome(batch[index], FAILED,
                                       reason=f"сбой — {errors.describe(error)}"))
                        finished.add(index)
                    if cancel is not None and cancel.is_set():
                        break
        except BrokenProcessPool:
            crashed = True
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as error:  # noqa: BLE001
            errors.report("пул обработки", error)
            crashed = True

        pending = [job for index, job in enumerate(batch) if index not in finished]
        if not pending or (cancel is not None and cancel.is_set()):
            break
        if not crashed:
            # пул отработал, но что-то осталось — например, отменили
            break
        if not processes_work:
            # ни одно задание не доехало: отдельные процессы в этой среде
            # недоступны — доделываем работу здесь, чтобы не потерять пачку
            errors.report(
                "рабочие процессы",
                RuntimeError("не удалось запустить обработку в отдельных процессах, "
                             "продолжаю в основном"))
            _run_here(pending, preset, task, record, cancel)
            return outcomes
        restarts += 1
        if restarts > MAX_POOL_RESTARTS:
            # пул падает уже который раз подряд — похоже на системную
            # проблему со средой, а не на конкретный файл. Дальше пересоздавать
            # его для каждого оставшегося файла по одному только замедляло бы
            # дело — доделываем без изоляции, но точно доделываем
            errors.report(
                "рабочие процессы",
                RuntimeError(f"пул падает подряд ({restarts} раз) — доделываю "
                             f"{len(pending)} файлов в текущем процессе"))
            _run_here(pending, preset, task, record, cancel)
            return outcomes
        if parallel > 1:
            # переходим на поштучный режим: так станет видно, кто именно упал
            errors.report("рабочий процесс",
                          RuntimeError("процесс обработки завершился аварийно, "
                                       "оставшиеся файлы идут по одному"))
            parallel = 1
            continue
        # в одиночном режиме виноват первый необработанный
        guilty = pending.pop(0)
        errors.log_only(f"падение на {guilty.title}",
                        RuntimeError("рабочий процесс завершился аварийно"))
        record(Outcome(guilty, FAILED, reason=CRASH_REASON))
    return outcomes
