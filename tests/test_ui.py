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


def test_only_checked_files_are_processed(window, tree, tmp_path):
    """Снятая галочка — это не «не выделено», а «не обрабатывать»."""
    window.add_paths([tree])
    spin()
    assert window.model.checked_count() == len(window.model.rows)

    window.model.set_all_checked(False)
    window.model.set_checked([0], True)
    spin()

    jobs = window.model.checked_jobs()
    assert len(jobs) == 1
    assert jobs[0][0] == 0
    assert window.start_button.isEnabled()

    window.model.set_all_checked(False)
    spin()
    assert not window.start_button.isEnabled()


def test_space_toggles_checks_on_the_whole_selection(window, tree):
    window.add_paths([tree])
    spin()

    window.model.set_all_checked(True)
    window.model.toggle_checked([0, 1])
    assert window.model.checked_count() == len(window.model.rows) - 2

    window.model.toggle_checked([0, 1])
    assert window.model.checked_count() == len(window.model.rows)


def test_theme_toggle_switches_both_styles_and_setting(window):
    from app.core.settings import THEME_DARK, THEME_LIGHT

    assert window.settings.theme == THEME_DARK
    window._toggle_theme()
    assert window.settings.theme == THEME_LIGHT
    assert window.model.theme == THEME_LIGHT

    window._toggle_theme()
    assert window.settings.theme == THEME_DARK


def test_footer_shows_the_output_folder_as_a_link(window, tmp_path):
    window._refresh_summary()
    assert str(tmp_path) in window.path_link.text()

    window.panel.output_field.setText("")
    window.settings = window.panel.collect()
    window._refresh_summary()
    assert "Выбрать папку" in window.path_link.text()


def test_exact_size_reaches_the_settings(window):
    from app.ui.settings_panel import SIZE_EXACT

    window.panel.size_buttons[SIZE_EXACT].setChecked(True)
    window.panel.width_spin.setValue(2000)
    window.panel.ratio_combo.setCurrentIndex(window.panel.ratio_combo.findData("2:3"))
    spin()

    settings = window.panel.collect()

    assert settings.exact_size_enabled
    assert settings.exact_size == (2000, 3000)
