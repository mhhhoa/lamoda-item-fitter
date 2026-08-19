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
