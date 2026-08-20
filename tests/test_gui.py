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


def _pump(window, timeout_ms=120000, analyze_only=False):
    """Крутит цикл событий, пока обработка не закончится."""
    loop = QEventLoop()
    original = window._on_thread_done

    def finished():
        original()
        loop.quit()

    window._on_thread_done = finished
    QTimer.singleShot(timeout_ms, loop.quit)
    QTimer.singleShot(0, lambda: window._start(analyze_only=analyze_only))
    loop.exec()


def test_window_processes_a_folder(qt_app, preset, photos, tmp_path):
    window = MainWindow(preset)
    window._output_root = tmp_path / "out"
    window.add_paths([photos])

    assert window.tree.topLevelItemCount() == 3
    # в списке видно исходное имя, суффикс появляется только у файла на диске
    assert window.tree.topLevelItem(0).text(0) == "фото0.jpg"

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


def _photos(tmp_path, count=3):
    from PIL import Image

    from tests.conftest import canvas

    folder = tmp_path / "пачка"
    folder.mkdir(exist_ok=True)
    for index in range(1, count + 1):
        array = canvas(900, 1400)
        array[500:700, 200:1100] = 60
        Image.fromarray(array).save(folder / f"{index}_фото.jpg")
    return folder


def test_all_files_are_checked_by_default(qt_app, preset, tmp_path):
    from PySide6.QtCore import Qt

    window = MainWindow(preset)
    window._output_root = tmp_path / "out"
    window.add_paths([_photos(tmp_path)])

    states = [window.tree.topLevelItem(i).checkState(0)
              for i in range(window.tree.topLevelItemCount())]

    assert states == [Qt.CheckState.Checked] * 3
    assert "Выбрано 3 из 3" in window.selection_label.text()
    window.close()


def test_unchecked_files_are_left_alone(qt_app, preset, tmp_path):
    """Снятая галочка — файл не обрабатывается и в папку результата не попадает."""
    from PySide6.QtCore import Qt

    window = MainWindow(preset)
    window._output_root = tmp_path / "out"
    window.add_paths([_photos(tmp_path)])
    window.tree.topLevelItem(1).setCheckState(0, Qt.CheckState.Unchecked)

    _pump(window)

    assert len(list((tmp_path / "out").rglob("*.jpg"))) == 2
    assert window.tree.topLevelItem(1).data(0, ROLE_OUTCOME) is None
    assert window.tree.topLevelItem(1).text(2) == "в очереди"
    window.close()


def test_nothing_checked_disables_the_buttons(qt_app, preset, tmp_path):
    window = MainWindow(preset)
    window._output_root = tmp_path / "out"
    window.add_paths([_photos(tmp_path)])

    window._set_all_checked(False)

    assert not window.run_button.isEnabled()
    assert not window.analyze_button.isEnabled()
    assert "Выбрано 0 из 3" in window.selection_label.text()
    window.close()


def test_analysis_reports_verdicts_without_writing_files(qt_app, preset, tmp_path):
    """«Анализ» показывает вердикт по каждому кадру и ничего не сохраняет."""
    from lamoda_item_fitter.fitter import FITTED

    window = MainWindow(preset)
    window._output_root = tmp_path / "out"
    window.add_paths([_photos(tmp_path)])

    _pump(window, analyze_only=True)

    for index in range(window.tree.topLevelItemCount()):
        item = window.tree.topLevelItem(index)
        outcome = item.data(0, ROLE_OUTCOME)
        assert outcome is not None and outcome.status == FITTED
        assert item.text(3), "вердикт обязан быть написан в строке"
    assert not (tmp_path / "out").exists(), "анализ не должен ничего писать на диск"
    assert "Анализ готов" in window.status.text()
    window.close()
