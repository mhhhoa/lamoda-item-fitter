"""Снимки интерфейса для инструкции коллегам.

Интерфейс снимается «вживую»: окно программы поднимается в offscreen-режиме
Qt, в него кладётся демонстрационная съёмка одного артикула, и снимки
сохраняются как есть. Поэтому в инструкции всегда те кнопки и подписи,
которые действительно есть в коде, а не нарисованные от руки.

Снять с нужной версии программы:

    git archive <тег или коммит> | tar -x -C /tmp/v11
    QT_QPA_PLATFORM=offscreen python docs/instruction/make_screens.py \\
        /tmp/v11 docs/instruction/screens reference /tmp/demo

Аргументы: исходники программы, куда класть снимки, папка с эталонами,
рабочая папка для демонстрационных файлов.
"""
import os, sys
from pathlib import Path

V11 = Path(sys.argv[1]); OUT = Path(sys.argv[2]); REF = Path(sys.argv[3]); TMP = Path(sys.argv[4])
OUT.mkdir(parents=True, exist_ok=True)
os.chdir(V11); sys.path.insert(0, str(V11))

from PIL import Image
from PySide6.QtWidgets import QApplication, QMessageBox

from lamoda_item_fitter.config import Preset
from lamoda_item_fitter.batch import COPY, inspect_one, process_one
from lamoda_item_fitter.gui.app import MainWindow
from lamoda_item_fitter.gui.settings import SettingsDialog

# Съёмка одного артикула: четыре кадра под подгонку и два крупных плана.
NAMES = {
    "MP002XW1M65L_33931210_1_v4_2x.webp": "Сандалии_1_сбоку.jpg",
    "MP002XW1M65L_33931216_2_v4_2x.webp": "Сандалии_2_пара.jpg",
    "MP002XW1M65L_33931217_3_v4_2x.webp": "Сандалии_3_сверху.jpg",
    "MP002XW1M65L_33931224_7_v4_2x.webp": "Сандалии_4_подошва.jpg",
    "MP002XW1M65L_33931218_4_v4_2x.webp": "Сандалии_5_крупно.jpg",
    "MP002XW1M65L_33931219_5_v4_2x.webp": "Сандалии_6_крупно.jpg",
}
folder = TMP / "Сандалии 44521"
folder.mkdir(parents=True, exist_ok=True)
for source, name in NAMES.items():
    Image.open(REF / source).convert("RGB").save(folder / name, quality=95)

results = TMP / "Загрузки"; results.mkdir(exist_ok=True)
WINDOWS_LOOK = Path(r"C:\Users\Иванова\Downloads")

app = QApplication([])
preset = Preset.load()
window = MainWindow(preset)
window._output_root = results
window.resize(1180, 780)
window.show()
window.add_paths([folder])

def settle(times=40):
    for _ in range(times):
        app.processEvents()

settle(); window._pool.waitForDone(30000); settle()
window._output_root = WINDOWS_LOOK
window._refresh_controls()
window.status.setText(f"В очереди {len(window._jobs)} файлов.")
settle()
window.grab().save(str(OUT / "01-ochered.png"))

for job in window._jobs:
    window._on_outcome(inspect_one(job, preset))
    settle(5)
window.status.setText("Анализ готов. подойдёт 4, перенесено как есть 2.")
window.tree.setCurrentItem(window.tree.topLevelItem(0))
settle()
window.grab().save(str(OUT / "02-analiz.png"))

for job in window._jobs:
    window._on_outcome(process_one(job, preset))
    settle(5)
window.status.setText("Готово. подогнано 4, перенесено как есть 2.")
window.tree.setCurrentItem(window.tree.topLevelItem(0))
settle()
window.grab().save(str(OUT / "03-gotovo.png"))

window.before_toggle.setChecked(True)
settle()
window.grab().save(str(OUT / "04-ishodnik.png"))

dialog = SettingsDialog(preset, None, COPY)
dialog.show(); settle()
dialog.grab().save(str(OUT / "05-nastroyki.png"))

box = QMessageBox()
box.setWindowTitle("Файлы уже существуют")
box.setText("В папке назначения уже есть 3 файлов с такими именами.")
box.setInformativeText("Что с ними сделать?")
for title, role in [("Сохранить копией", QMessageBox.ButtonRole.AcceptRole),
                    ("Перезаписать", QMessageBox.ButtonRole.DestructiveRole),
                    ("Пропустить", QMessageBox.ButtonRole.RejectRole),
                    ("Отмена", QMessageBox.ButtonRole.NoRole)]:
    box.addButton(title, role)
box.setStyleSheet(window.styleSheet())
box.show(); settle()
box.grab().save(str(OUT / "06-konflikt.png"))
print("снимки готовы")
