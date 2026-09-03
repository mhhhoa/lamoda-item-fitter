"""Падение рабочего процесса не останавливает очередь.

Это ядро обещания «программа не закрывается ни при каких файлах»: сбой на
уровне системы невозможно перехватить из Python, поэтому обработка вынесена
в отдельные процессы.
"""

import pytest
from PIL import Image

from lamoda_item_fitter.batch import COPY, FAILED, apply_policy, plan, summarize
from lamoda_item_fitter.fitter import FITTED
from lamoda_item_fitter.runner import CRASH_REASON, run_isolated
from tests.conftest import canvas
from tests.crashers import POISON, exit_task, ok_task, segfault_task


@pytest.fixture
def batch(tmp_path):
    """Шесть файлов, четвёртый — ядовитый: ровно сценарий из отчёта."""
    folder = tmp_path / "пачка"
    folder.mkdir()
    names = ["1_фото", "2_фото", "3_фото", f"4_{POISON}", "5_фото", "6_фото"]
    for name in names:
        array = canvas(900, 1400)
        array[500:700, 200:1100] = 60
        Image.fromarray(array).save(folder / f"{name}.jpg")
    return folder


def _run(batch_folder, preset, tmp_path, task, workers=3):
    jobs, _ = apply_policy(
        plan([batch_folder], preset, output_root=tmp_path / "out"), COPY)
    return run_isolated(jobs, preset, task, workers=workers), jobs


@pytest.mark.parametrize("task", [exit_task, segfault_task],
                         ids=["процесс убит", "сегфолт"])
def test_dead_worker_does_not_stop_the_queue(batch, preset, tmp_path, task):
    outcomes, jobs = _run(batch, preset, tmp_path, task)

    assert len(outcomes) == len(jobs), "очередь обязана дойти до конца"
    counts = summarize(outcomes)
    assert counts[FITTED] == 5, "пять здоровых файлов должны обработаться"
    assert counts[FAILED] == 1

    broken = next(o for o in outcomes if o.status == FAILED)
    assert POISON in broken.job.source.name, "виновник определён верно"
    assert broken.reason == CRASH_REASON
    assert len(list((tmp_path / "out").rglob("*.jpg"))) == 5


def test_healthy_batch_runs_in_parallel(batch, preset, tmp_path):
    outcomes, jobs = _run(batch, preset, tmp_path, ok_task)

    assert len(outcomes) == len(jobs)
    assert summarize(outcomes)[FITTED] == 6


def test_results_arrive_one_by_one(batch, preset, tmp_path):
    seen = []
    jobs, _ = apply_policy(plan([batch], preset, output_root=tmp_path / "out"), COPY)

    run_isolated(jobs, preset, exit_task, on_result=seen.append, workers=3)

    assert len(seen) == len(jobs), "интерфейс узнаёт о каждом файле, включая сбойный"


def test_falls_back_to_current_process_when_spawning_fails(
    batch, preset, tmp_path, monkeypatch
):
    """Если отдельные процессы запустить нельзя, пачка всё равно обрабатывается.

    Так бывает, когда защитное ПО не даёт программе порождать копии себя:
    изоляции в этом случае нет, но работать программа обязана.
    """
    from lamoda_item_fitter import runner as runner_mod
    from lamoda_item_fitter.batch import process_one

    def forbidden(*args, **kwargs):
        raise OSError("создание процессов запрещено")

    monkeypatch.setattr(runner_mod, "ProcessPoolExecutor", forbidden)

    jobs, _ = apply_policy(plan([batch], preset, output_root=tmp_path / "out"), COPY)
    outcomes = run_isolated(jobs, preset, process_one, workers=3)

    assert len(outcomes) == len(jobs), "запасной путь обязан доделать всю пачку"
    assert summarize(outcomes)[FITTED] == 6
    assert len(list((tmp_path / "out").rglob("*.jpg"))) == 6


def test_pool_that_never_starts_is_not_retried_per_file(
    preset, tmp_path, monkeypatch,
):
    """Если пул вообще не поднимается, программа не пробует поднять его
    заново под каждый файл по отдельности — ровно тот сценарий, что раньше
    превращал большую пачку в лавину попыток. Дополнительно, для случая,
    когда пул стартует, но продолжает падать при повторных попытках, в
    run_isolated есть потолок MAX_POOL_RESTARTS — после него работа тоже
    доделывается без изоляции, а не пересоздаёт пул на каждый оставшийся
    файл; отдельным мок-тестом это не покрыто, так как «последний рубеж»
    (_run_here) выполняет задания напрямую, и настоящий крах процесса оттуда
    в принципе не поймать из Python — эта часть проверена вручную и
    трассировкой кода, не автотестом."""
    import lamoda_item_fitter.runner as runner_mod
    from lamoda_item_fitter.batch import COPY, apply_policy, plan, process_one
    from lamoda_item_fitter.runner import MAX_POOL_RESTARTS
    from concurrent.futures.process import BrokenProcessPool

    folder = tmp_path / "пачка"
    folder.mkdir()
    for index in range(3):
        array = canvas(900, 1400)
        array[500:700, 200:1100] = 60
        Image.fromarray(array).save(folder / f"{index}.jpg")

    class AlwaysBrokenPool:
        """Подмена пула: любое обращение сразу рапортует о поломке."""

        attempts = 0

        def __init__(self, *a, **k):
            AlwaysBrokenPool.attempts += 1
            raise BrokenProcessPool("подставной крах пула")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fallback_calls = []
    original_run_here = runner_mod._run_here

    def spy_run_here(jobs, preset, task, record, cancel):
        fallback_calls.append(list(jobs))
        return original_run_here(jobs, preset, task, record, cancel)

    monkeypatch.setattr(runner_mod, "ProcessPoolExecutor", AlwaysBrokenPool)
    monkeypatch.setattr(runner_mod, "_run_here", spy_run_here)

    jobs, _ = apply_policy(plan([folder], preset, output_root=tmp_path / "out"), COPY)
    outcomes = runner_mod.run_isolated(jobs, preset, process_one, workers=3)

    # пул так и не поднялся ни разу, поэтому это ветка «процессы недоступны
    # вообще» — она срабатывает раньше счётчика restarts, но так же надёжно
    # ограничивает число попыток одним разом, а не по файлу
    assert AlwaysBrokenPool.attempts == 1, "пул не должен пересоздаваться бесконечно"
    assert len(fallback_calls) == 1
    assert len(outcomes) == len(jobs), "очередь обязана дойти до конца"
    assert summarize(outcomes)[FITTED] == 3
