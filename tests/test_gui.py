"""Интерфейс: собирается, проводит пакет и показывает результат.

Тест headless (offscreen), поэтому годится и для CI: он ловит поломки сигналов
и разъехавшиеся вызовы Qt, которые иначе всплыли бы только у пользователя.
"""

import os
from pathlib import Path

import pytest
from PIL import Image

from tests.conftest import canvas

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 не установлен")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lamoda_item_fitter.fitter import FITTED  # noqa: E402
from lamoda_item_fitter.gui.app import ROLE_OUTCOME, MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def photos(tmp_path):
    folder = tmp_path / "Артикул 7"
    folder.mkdir()
    for index in range(3):
        array = canvas(900, 1400)
        array[500:700, 200 + index * 20:1100] = 60
        Image.fromarray(array).save(folder / f"фото{index}.jpg")
    return folder


def _pump(window, timeout_ms=60000):
    """Крутит цикл событий, пока обработка не закончится."""
    loop = QEventLoop()
    original = window._on_thread_done

    def finished():
        original()
        loop.quit()

    window._on_thread_done = finished
    QTimer.singleShot(timeout_ms, loop.quit)
    QTimer.singleShot(0, window._start)
    loop.exec()


def test_window_processes_a_folder(qt_app, preset, photos, tmp_path):
    window = MainWindow(preset)
    window._output_root = tmp_path / "out"
    window.add_paths([photos])

    assert window.tree.topLevelItemCount() == 3
    assert str(window.tree.topLevelItem(0).text(0)).endswith("_lamodafit.jpg")

    _pump(window)

    statuses = []
    for index in range(window.tree.topLevelItemCount()):
        item = window.tree.topLevelItem(index)
        outcome = item.data(0, ROLE_OUTCOME)
        assert outcome is not None, "строка осталась без результата"
        statuses.append(outcome.status)
        assert outcome.job.destination.exists()
        assert outcome.metrics.margins["bottom"] == preset.margins.bottom

    assert statuses == [FITTED] * 3
    assert "подогнано 3" in window.status.text()
    window.close()


def test_preview_shows_the_result(qt_app, preset, photos, tmp_path):
    window = MainWindow(preset)
    window._output_root = tmp_path / "out"
    window.add_paths([photos])
    _pump(window)

    window.tree.setCurrentItem(window.tree.topLevelItem(0))
    window._update_preview()

    assert window.preview.has_before
    assert window.before_toggle.isEnabled()
    window.close()


def test_clearing_empties_the_queue(qt_app, preset, photos, tmp_path):
    window = MainWindow(preset)
    window._output_root = tmp_path / "out"
    window.add_paths([photos])

    window._clear()

    assert window.tree.topLevelItemCount() == 0
    assert not window.run_button.isEnabled()
    window.close()


def test_queue_is_locked_while_processing(qt_app, preset, photos, tmp_path):
    """Пересборка очереди на ходу оборвала бы связь строк с результатами."""
    window = MainWindow(preset)
    window._output_root = tmp_path / "out"
    window.add_paths([photos])
    window._thread = object()  # притворяемся, что обработка идёт

    window.add_paths([photos / "фото0.jpg"])

    assert window.tree.topLevelItemCount() == 3
    assert "дождитесь" in window.status.text()
    window._thread = None
    window.close()


def test_broken_file_in_the_middle_does_not_stop_the_queue(qt_app, preset, tmp_path):
    """Сценарий пользователя: 6 файлов, четвёртый сбойный.

    Раньше окно закрывалось и файлы после сбойного не обрабатывались вовсе.
    Теперь все шесть строк обязаны получить статус, а годные — сохраниться.
    """
    from PIL import Image

    from lamoda_item_fitter.batch import FAILED
    from tests.conftest import canvas

    folder = tmp_path / "пачка"
    folder.mkdir()
    for index in (1, 2, 3, 5, 6):
        array = canvas(900, 1400)
        array[500:700, 200:1100] = 60
        Image.fromarray(array).save(folder / f"{index}_фото.jpg")
    (folder / "4_фото.jpg").write_text("не картинка", encoding="utf-8")

    window = MainWindow(preset)
    window._output_root = tmp_path / "out"
    window.add_paths([folder])
    assert window.tree.topLevelItemCount() == 6

    _pump(window)

    statuses = {}
    for index in range(window.tree.topLevelItemCount()):
        item = window.tree.topLevelItem(index)
        outcome = item.data(0, ROLE_OUTCOME)
        assert outcome is not None, f"строка {item.text(0)} осталась без статуса"
        assert item.text(2), "статус в строке обязан быть заполнен"
        assert item.text(3), "причина в строке обязана быть заполнена"
        statuses[item.text(0)] = outcome.status

    assert sum(1 for s in statuses.values() if s == FITTED) == 5
    assert sum(1 for s in statuses.values() if s == FAILED) == 1
    assert len(list((tmp_path / "out").rglob("*.jpg"))) == 5
    assert "подогнано 5" in window.status.text()
    window.close()


def test_unrecognised_photo_shows_a_reason_in_the_row(qt_app, preset, tmp_path):
    import numpy as np
    from PIL import Image

    from lamoda_item_fitter.fitter import UNRECOGNIZED
    from tests.conftest import canvas

    folder = tmp_path / "пачка"
    folder.mkdir()
    array = canvas(2400, 3200, 249)
    array[1200:1215, 1600:1620] = 40      # пылинка вместо товара
    Image.fromarray(array).save(folder / "случайное.jpg")

    window = MainWindow(preset)
    window._output_root = tmp_path / "out"
    window.add_paths([folder])
    _pump(window)

    item = window.tree.topLevelItem(0)
    assert item.data(0, ROLE_OUTCOME).status == UNRECOGNIZED
    assert item.text(2) == "не распознан"
    assert item.text(3)
    window.close()
