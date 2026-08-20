"""Программа не закрывается ни при каких исходниках.

Причина требования простая: у пользователя окно исчезало посреди пакета, и
файлы после сбойного не обрабатывались вовсе. Ни один кадр не имеет права
остановить очередь.
"""

import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lamoda_item_fitter import errors
from lamoda_item_fitter.batch import COPY, FAILED, apply_policy, plan, process_one, summarize
from lamoda_item_fitter.fitter import FITTED, UNRECOGNIZED, fit_image
from lamoda_item_fitter.runner import run_isolated
from tests.conftest import as_image, canvas
from tests.crashers import POISON, raise_task

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def product_photo(path: Path) -> Path:
    array = canvas(900, 1400)
    array[500:700, 200:1100] = 60
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array).save(path)
    return path


def random_photo(path: Path, seed: int = 5) -> Path:
    """Не предметный кадр: градиент, шум и тёмные пятна во весь кадр."""
    rng = np.random.default_rng(seed)
    array = np.tile(np.linspace(30, 210, 1600, dtype=np.uint8)[None, :, None], (1200, 1, 3))
    array = np.clip(array.astype(np.int16) + rng.integers(-25, 25, array.shape), 0, 255)
    array[300:900, 200:700] = rng.integers(0, 90, (600, 500, 3))
    Image.fromarray(array.astype(np.uint8)).save(path)
    return path


# --- ядро: непригодные кадры отбраковываются, а не растягиваются -------------

def test_speck_is_not_treated_as_an_item(preset):
    """Пылинка на пустом кадре — не товар: растянуть её значило бы съесть память."""
    array = canvas(2400, 3200, 249)
    array[1200:1215, 1600:1620] = 40

    result = fit_image(as_image(array), preset)

    assert result.status == UNRECOGNIZED
    assert "не предметное фото" in result.reason or "мелкий" in result.reason


def test_tiny_source_is_refused_not_upscaled(preset):
    array = canvas(300, 400, 249)
    array[150:170, 180:220] = 40

    result = fit_image(as_image(array), preset)

    assert result.status == UNRECOGNIZED
    assert "увеличение" in result.reason


def test_empty_frame_is_unrecognized(preset):
    result = fit_image(as_image(canvas(900, 1400, 249)), preset)

    assert result.status == UNRECOGNIZED
    assert result.reason


# --- пакет: сбой одного файла не останавливает остальные ---------------------

def test_exploding_file_does_not_stop_the_batch(tmp_path, preset):
    """Исключение в одном задании не мешает остальным дойти до конца."""
    folder = tmp_path / "пачка"
    for index in (1, 2, 3, 5, 6):
        product_photo(folder / f"{index}_фото.jpg")
    product_photo(folder / f"4_{POISON}.jpg")

    jobs, _ = apply_policy(plan([folder], preset, output_root=tmp_path / "out"), COPY)
    outcomes = run_isolated(jobs, preset, raise_task, workers=2)
    counts = summarize(outcomes)

    assert len(outcomes) == 6, "очередь обязана дойти до конца"
    assert counts[FITTED] == 5
    assert counts[FAILED] == 1
    broken = next(o for o in outcomes if o.status == FAILED)
    assert "сломанный кадр" in broken.reason


def test_unreadable_file_between_good_ones(tmp_path, preset):
    folder = tmp_path / "пачка"
    product_photo(folder / "1.jpg")
    (folder / "2.jpg").write_text("это не картинка", encoding="utf-8")
    product_photo(folder / "3.jpg")

    jobs, _ = apply_policy(plan([folder], preset, output_root=tmp_path / "out"), COPY)
    outcomes = run_isolated(jobs, preset, process_one, workers=2)

    assert len(outcomes) == 3
    assert summarize(outcomes)[FITTED] == 2
    assert summarize(outcomes)[FAILED] == 1


def test_random_photo_gets_a_reason_not_a_crash(tmp_path, preset):
    folder = tmp_path / "пачка"
    product_photo(folder / "1.jpg")
    random_photo(folder / "2.jpg")
    product_photo(folder / "3.jpg")

    jobs, _ = apply_policy(plan([folder], preset, output_root=tmp_path / "out"), COPY)
    outcomes = run_isolated(jobs, preset, process_one, workers=2)

    assert len(outcomes) == 3
    odd = next(o for o in outcomes if o.job.source.name == "2.jpg")
    assert odd.status != FITTED
    assert odd.reason, "у необработанного файла обязана быть внятная причина"


def test_failing_listener_does_not_break_the_batch(tmp_path, preset):
    """Сбой в уведомлении интерфейса не должен утаскивать за собой пакет."""
    folder = tmp_path / "пачка"
    for index in (1, 2, 3):
        product_photo(folder / f"{index}.jpg")

    def bad_listener(outcome):
        raise RuntimeError("интерфейс упал")

    jobs, _ = apply_policy(plan([folder], preset, output_root=tmp_path / "out"), COPY)
    outcomes = run_isolated(jobs, preset, process_one, on_result=bad_listener, workers=2)

    assert summarize(outcomes)[FITTED] == 3


# --- защита слотов -----------------------------------------------------------

def test_guard_swallows_and_reports():
    seen: list[str] = []
    errors.add_listener(seen.append)

    @errors.guard("тестовый слот")
    def boom():
        raise ValueError("бум")

    assert boom() is None
    assert any("тестовый слот" in message for message in seen)
