"""Готовит собранную папку к раздаче: раскладывает всё, что нужно коллеге.

Зачем это нужно. PyInstaller в режиме onedir выдаёт папку, где рядом с exe
лежит служебная папка _internal. Проводник Windows показывает папки выше
файлов, поэтому первое, что видит человек, открывший сборку, — это _internal;
он заходит внутрь, находит там сотню библиотек и не понимает, что запускать.
Плюс архив из Actions распаковывается «как есть»: без обёртки exe и _internal
высыпались бы прямо в «Загрузки».

Поэтому в папку к программе кладутся:

* «!! КАК ЗАПУСТИТЬ.txt» — с чего начать;
* «Создать ярлык на рабочем столе.bat» — зовёт программу с ключом
  --create-shortcut. Отдельного exe-установщика нет намеренно: второй
  неподписанный exe означал бы второе окно SmartScreen у каждого коллеги;
* инструкция в Word — чтобы её не искали в переписке;
* а в саму _internal — записка, что программа уровнем выше.

Вся сборка кладётся в package/LamodaItemFitter/, рядом короткая памятка:
архив тогда распаковывается одной аккуратной папкой.

Восклицательные знаки в именах — чтобы подсказка стояла в списке первой:
знаки препинания Проводник сортирует раньше букв.

Запуск после сборки:  python tools/prepare_package.py
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: имя exe несёт номер версии, поэтому ищем по маске, а не по точному имени
EXE_GLOB = "LamodaItemFitter*.exe"
#: имя без версии — оно встречается в текстах памяток и заменяется на настоящее
EXE_PLACEHOLDER = "LamodaItemFitter.exe"
CONTENTS_DIR = "_internal"

# Собранный exe запускается прямо на сборочной машине — самопроверкой; свои
# рабочие файлы он пишет рядом с собой, и они норовят уехать коллегам:
# лог с чужими сообщениями и настройки, которые перебили бы значения
# по умолчанию у каждого, кто распакует папку.
RUNTIME_LEFTOVERS = ("LamodaItemFitter.log", "LamodaItemFitter.settings.json")

# Слева — файл в репозитории, справа — имя, под которым он попадёт в сборку.
START_HERE = ("start_here.txt", "!! КАК ЗАПУСТИТЬ.txt")
INTERNAL_NOTE = ("internal_note.txt", "!! ЗДЕСЬ НИЧЕГО ЗАПУСКАТЬ НЕ НУЖНО.txt")
ZIP_README = ("zip_readme.txt", "!! КАК ЗАПУСТИТЬ.txt")
SHORTCUT_BAT = ("create_shortcut.bat", "Создать ярлык на рабочем столе.bat")

INSTRUCTION = ROOT / "docs" / "instruction" / "Инструкция — Lamoda Item Fitter.docx"


def app_version() -> str:
    """Версия из пакета — единственное место, где она задана."""
    source = (ROOT / "lamoda_item_fitter" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', source).group(1)


def find_exe(dist_dir: Path) -> Path:
    matches = sorted(dist_dir.glob(EXE_GLOB))
    if not matches:
        raise SystemExit(
            f"в {dist_dir} нет файла по маске {EXE_GLOB} — похоже, сборка не прошла "
            f"или путь указан неверно")
    return matches[0]


def _put_file(source: Path, target_dir: Path, display_name: str, exe_name: str) -> Path:
    """Кладёт файл в папку под его «человеческим» именем.

    Копируем байт в байт: в исходниках уже стоят BOM и переводы строк CRLF,
    без которых старый Блокнот показывает кракозябры. Заодно подставляем
    настоящее имя exe — оно меняется с каждой версией, и памятка, зовущая
    несуществующий файл, хуже отсутствующей.
    """
    data = source.read_bytes()
    if exe_name != EXE_PLACEHOLDER:
        data = data.replace(EXE_PLACEHOLDER.encode("utf-8"), exe_name.encode("utf-8"))
    destination = target_dir / display_name
    destination.write_bytes(data)
    return destination


def instruction_version(path: Path) -> str | None:
    """Версия, о которой рассказывает инструкция.

    Читаем текст документа: инструкция показывает номер версии на титуле и
    скриншоты именно той сборки, поэтому уехавшая версия — это не мелочь,
    а неверная инструкция в руках у коллеги.
    """
    try:
        with zipfile.ZipFile(path) as document:
            xml = document.read("word/document.xml").decode("utf-8", "ignore")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    text = " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
    found = re.search(r"версия\s+([0-9][0-9.]*)", text)
    return found.group(1) if found else None


def prepare(dist_dir: Path, package_dir: Path, docs: Path | None = None,
            instruction: Path | None = None) -> Path:
    """Раскладывает всё нужное в dist_dir и собирает package_dir для раздачи."""
    docs = docs or ROOT / "docs"
    instruction = INSTRUCTION if instruction is None else instruction

    exe = find_exe(dist_dir)
    version = app_version()

    for name in RUNTIME_LEFTOVERS:
        stray = dist_dir / name
        if stray.is_file():
            stray.unlink()
            print(f"убран след самопроверки: {name}")

    _put_file(docs / START_HERE[0], dist_dir, START_HERE[1], exe.name)
    _put_file(docs / SHORTCUT_BAT[0], dist_dir, SHORTCUT_BAT[1], exe.name)

    if instruction is not None:
        if not instruction.is_file():
            raise SystemExit(f"инструкция не найдена: {instruction}")
        told = instruction_version(instruction)
        if told != version:
            raise SystemExit(
                f"инструкция рассказывает про версию {told}, а собирается {version} — "
                f"пересоберите её: node docs/instruction/make_docx.js")
        shutil.copy2(instruction, dist_dir / instruction.name)

    contents = dist_dir / CONTENTS_DIR
    if contents.is_dir():
        _put_file(docs / INTERNAL_NOTE[0], contents, INTERNAL_NOTE[1], exe.name)
    else:
        print(f"внимание: папки {CONTENTS_DIR} нет, подсказка в неё не положена")

    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)
    shutil.copytree(dist_dir, package_dir / dist_dir.name)
    _put_file(docs / ZIP_README[0], package_dir, ZIP_README[1], exe.name)
    return package_dir


def main(argv: list[str] | None = None) -> int:
    _speak_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist" / "LamodaItemFitter")
    parser.add_argument("--package", type=Path, default=ROOT / "package")
    args = parser.parse_args(argv)

    package = prepare(args.dist.resolve(), args.package.resolve())
    print(f"папка к раздаче: {package}")
    for item in sorted(package.iterdir(), key=lambda p: (p.is_file(), p.name)):
        print(f"  {item.name}{'/' if item.is_dir() else ''}")
    return 0


def _speak_utf8() -> None:
    """Разрешает выводить кириллицу.

    На Windows Python пишет в перенаправленный вывод в кодировке системы
    (cp1252 на англоязычном раннере), и любая русская строка в print роняет
    скрипт с UnicodeEncodeError — на этом упала первая сборка v1.2.1.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    sys.exit(main())
