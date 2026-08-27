"""Проверки окна: то, что ломается при повторных переключениях и закрытии."""

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from app.core.settings import Settings
from app.ui.main_window import MainWindow
from app.ui.theme import stylesheet


@pytest.fixture(scope="session")
def qt_app():
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(stylesheet())
    return application


@pytest.fixture(scope="session", autouse=True)
def silence_dialogs(qt_app):
    """Модальный вопрос при закрытии некому подтвердить — тест повиснет.

    Подмена на всю сессию: разбор фикстуры окна происходит после отката
    monkeypatch, и вопрос всплыл бы именно там.
    """
    QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.Yes)
    QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.Ok)


@pytest.fixture
def window(qt_app, tmp_path):
    settings = Settings(output_dir=str(tmp_path / "out"))
    widget = MainWindow(settings)
    widget.show()
    yield widget
    # Иначе закрытие окна с живой очередью поднимет модальный вопрос,
    # который в тестах некому подтвердить.
    widget.pipeline.cancel()
    widget.pipeline.wait()
    widget.close()


def spin(times: int = 10) -> None:
    for _ in range(times):
        QCoreApplication.processEvents()


def test_drop_zone_survives_repeated_switching(window, tree):
    """Список то наполняется, то очищается — зона переключает вид каждый раз."""
    for _ in range(4):
        window.add_paths([tree])
        spin()
        compact = window.drop_zone.height()

        window._clear()
        spin()
        full = window.drop_zone.height()

        assert compact < full

    window.add_paths([tree])
    spin()
    visible = [b.text() for b in window.drop_zone.findChildren(QPushButton) if b.isVisible()]
    assert visible == ["Выбрать файлы", "Выбрать папку"]


def test_stylesheet_resolves_asset_paths():
    css = stylesheet()
    assert "check.png" in css and "chevron_down.png" in css


def test_closing_while_working_waits_for_the_queue(window, tree):
    # Одного небольшого файла достаточно: важно, что окно закрывается на
    # живой очереди, а не сколько именно работы в ней стоит.
    window.add_paths([tree / "dress_blue" / "back.jpg"])
    spin()
    window.panel.limit_spin.setValue(0.2)
    window._start()

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert not window.pipeline.running


def test_settings_survive_a_round_trip(window, tmp_path):
    window.panel.limit_spin.setValue(2.5)
    window.panel.max_side_spin.setValue(1800)
    window.panel.metadata_check.setChecked(True)
    window.panel.flat_radio.setChecked(True)
    spin()

    settings = window.panel.collect()

    assert settings.target_mb == 2.5
    assert settings.max_side == 1800
    assert settings.keep_metadata is True
    assert settings.keep_structure is False
