"""Готовит собранную папку к раздаче: раскладывает подсказки и оборачивает её.

Зачем это нужно. PyInstaller в режиме onedir выдаёт папку, где рядом с
LamodaItemFitter.exe лежит служебная папка _internal. Проводник Windows
показывает папки выше файлов, поэтому первое, что видит человек, открывший
сборку, — это _internal; он заходит внутрь, находит там сотню библиотек и не
понимает, что запускать. Плюс архив из Actions распаковывается «как есть»:
без обёртки exe и _internal высыпаются прямо в «Загрузки».

Поэтому:

* в корень сборки кладётся «!! КАК ЗАПУСТИТЬ.txt» — с чего начать;
* в _internal кладётся «!! ЗДЕСЬ НИЧЕГО ЗАПУСКАТЬ НЕ НУЖНО.txt» — она
  встречает того, кто всё-таки открыл служебную папку, и отправляет обратно;
* вся сборка кладётся в package/LamodaItemFitter/, а рядом — короткая
  памятка. Архив тогда распаковывается одной аккуратной папкой.

Восклицательные знаки в именах — чтобы подсказка стояла в списке первой:
знаки препинания Проводник сортирует раньше букв.

Запуск после сборки:  python tools/prepare_package.py
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXE_NAME = "LamodaItemFitter.exe"
CONTENTS_DIR = "_internal"

# Слева — файл в репозитории, справа — имя, под которым он попадёт в сборку.
START_HERE = ("start_here.txt", "!! КАК ЗАПУСТИТЬ.txt")
INTERNAL_NOTE = ("internal_note.txt", "!! ЗДЕСЬ НИЧЕГО ЗАПУСКАТЬ НЕ НУЖНО.txt")
ZIP_README = ("zip_readme.txt", "!! КАК ЗАПУСТИТЬ.txt")


def _put_note(docs: Path, note: tuple[str, str], target_dir: Path) -> Path:
    """Кладёт подсказку в папку под её «человеческим» именем.

    Копируем байт в байт: в исходниках уже стоят BOM и переводы строк CRLF,
    без которых старый Блокнот показывает кракозябры и одну длинную строку.
    """
    source_name, display_name = note
    destination = target_dir / display_name
    destination.write_bytes((docs / source_name).read_bytes())
    return destination


def prepare(dist_dir: Path, package_dir: Path, docs: Path | None = None) -> Path:
    """Раскладывает подсказки в dist_dir и собирает package_dir для раздачи."""
    docs = docs or ROOT / "docs"

    if not (dist_dir / EXE_NAME).is_file():
        raise SystemExit(
            f"в {dist_dir} нет {EXE_NAME} — похоже, сборка не прошла или "
            f"путь указан неверно"
        )

    _put_note(docs, START_HERE, dist_dir)

    contents = dist_dir / CONTENTS_DIR
    if contents.is_dir():
        _put_note(docs, INTERNAL_NOTE, contents)
    else:
        print(f"внимание: папки {CONTENTS_DIR} нет, подсказка в неё не положена")

    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)
    shutil.copytree(dist_dir, package_dir / dist_dir.name)
    _put_note(docs, ZIP_README, package_dir)
    return package_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist" / "LamodaItemFitter")
    parser.add_argument("--package", type=Path, default=ROOT / "package")
    args = parser.parse_args(argv)

    package = prepare(args.dist.resolve(), args.package.resolve())
    print(f"папка к раздаче: {package}")
    for item in sorted(package.iterdir(), key=lambda p: (p.is_file(), p.name)):
        print(f"  {item.name}{'/' if item.is_dir() else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
