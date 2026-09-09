"""Настройки: что человек выставил в диалоге, то и применяется — и переживает
закрытие программы.

Ошибки здесь тихие: файл сохранится, просто не с тем весом или качеством, и
заметит это уже модерация Ламоды.
"""

import os

import pytest

from lamoda_item_fitter.user_settings import UserSettings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 не установлен")

from PySide6.QtWidgets import QApplication  # noqa: E402

from lamoda_item_fitter.gui.settings import MEGABYTE, SettingsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qt_app, preset):
    window = SettingsDialog(preset, None, "copy")
    yield window
    window.deleteLater()


def test_weight_starts_at_the_lamoda_limit(dialog):
    """Пять мегабайт — то, что принимает Ламода, и то, что видит человек."""
    assert dialog.max_weight.value() == pytest.approx(5.0)
    assert dialog.max_weight.suffix().strip() == "МБ"


def test_chosen_weight_reaches_the_preset(dialog, preset):
    dialog.max_weight.setValue(2.5)

    assert dialog.result_preset().output.max_bytes == int(2.5 * MEGABYTE)


def test_weight_survives_a_restart(tmp_path, preset):
    """Настройки живут в файле рядом с exe, а не только до закрытия окна."""
    changed = preset.replace(output=preset.output.__class__(
        **{**preset.output.__dict__, "max_bytes": 3 * MEGABYTE}))
    target = tmp_path / "LamodaItemFitter.settings.json"

    UserSettings.from_state(changed, "copy", None).save(target)
    restored = UserSettings.load(target).apply(preset)

    assert restored.output.max_bytes == 3 * MEGABYTE


def test_settings_file_from_an_older_version_still_opens(tmp_path, preset):
    """Файл, записанный сборкой без лимита веса, не должен ронять запуск."""
    target = tmp_path / "LamodaItemFitter.settings.json"
    target.write_text('{"format": "jpeg", "jpeg_quality": 92}', encoding="utf-8")

    restored = UserSettings.load(target).apply(preset)

    assert restored.output.jpeg_quality == 92
    assert restored.output.max_bytes == 5 * MEGABYTE


def test_hint_explains_the_tradeoff(dialog):
    """Подсказка видима и говорит про качество — её просили текстом, не наведением."""
    assert dialog.weight_hint.isVisibleTo(dialog)
    assert "качество" in dialog.weight_hint.text()


def test_hints_are_not_clipped(dialog):
    """Подсказку, которую не дочитать, лучше бы не писать вовсе.

    Перенос по словам сам по себе высоты строке не добавляет: подпись отдаёт
    высоту одной строки, и хвост фразы обрезается прямо посреди слова.
    """
    dialog.show()
    dialog.adjustSize()
    QApplication.processEvents()

    hints = (dialog.quality_hint, dialog.weight_hint, dialog.shortcut_hint,
             dialog.cropped_hint, dialog.fit_mode_hint)
    for hint in hints:
        assert hint.text()
        assert hint.height() >= hint.heightForWidth(hint.width()), hint.text()
