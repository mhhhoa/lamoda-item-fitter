"""Как выглядит сборка глазами того, кто открыл её впервые.

Коллега, распаковавший архив, попадает в папку, где Проводник показывает
служебную _internal выше exe. Тесты держат раскладку подсказок, которая
выводит его к программе, и следят за кодировкой: без BOM и CRLF Блокнот
показывает кракозябры, а подсказка нужна ровно тем, кто читает её Блокнотом.
"""

import io
import sys
from pathlib import Path

import pytest

from tools.prepare_package import (
    EXE_NAME,
    INTERNAL_NOTE,
    START_HERE,
    ZIP_README,
    main,
    prepare,
)

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


@pytest.fixture
def built(tmp_path):
    """Изображает то, что оставляет после себя PyInstaller."""
    dist = tmp_path / "dist" / "LamodaItemFitter"
    (dist / "_internal" / "PySide6").mkdir(parents=True)
    (dist / EXE_NAME).write_bytes(b"MZ")
    (dist / "_internal" / "python312.dll").write_bytes(b"MZ")
    return dist


@pytest.mark.parametrize("source_name", [START_HERE[0], INTERNAL_NOTE[0], ZIP_README[0]])
def test_notes_are_readable_in_notepad(source_name):
    raw = (DOCS / source_name).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "без BOM Блокнот покажет кракозябры"
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), "нужен CRLF"
    raw.decode("utf-8")


def test_every_note_points_at_the_exe():
    for source_name, _ in (START_HERE, INTERNAL_NOTE, ZIP_README):
        assert EXE_NAME in (DOCS / source_name).read_text(encoding="utf-8-sig")


def test_hints_land_where_a_lost_person_looks(built, tmp_path):
    package = prepare(built, tmp_path / "package")

    # Первый экран после распаковки: одна папка и памятка рядом с ней.
    assert sorted(p.name for p in package.iterdir()) == sorted(
        ["LamodaItemFitter", ZIP_README[1]]
    )
    # Внутри папки — подсказка рядом с exe.
    assert (package / "LamodaItemFitter" / START_HERE[1]).is_file()
    assert (package / "LamodaItemFitter" / EXE_NAME).is_file()
    # И в служебной папке, куда человек уходит искать программу.
    assert (package / "LamodaItemFitter" / "_internal" / INTERNAL_NOTE[1]).is_file()
    assert (package / "LamodaItemFitter" / "_internal" / "python312.dll").is_file()


def test_hints_sort_above_the_exe(built, tmp_path):
    """Проводник ставит знаки препинания выше букв — подсказка идёт первой."""
    package = prepare(built, tmp_path / "package")
    folder = package / "LamodaItemFitter"
    files = sorted((p.name for p in folder.iterdir() if p.is_file()))
    assert files[0] == START_HERE[1]


def test_second_run_does_not_pile_up(built, tmp_path):
    prepare(built, tmp_path / "package")
    package = prepare(built, tmp_path / "package")
    assert not (package / "LamodaItemFitter" / "LamodaItemFitter").exists()


def test_build_without_exe_is_reported(tmp_path):
    empty = tmp_path / "dist" / "LamodaItemFitter"
    empty.mkdir(parents=True)
    with pytest.raises(SystemExit, match=EXE_NAME):
        prepare(empty, tmp_path / "package")


def test_report_survives_windows_console(built, tmp_path, monkeypatch):
    """Отчёт печатается по-русски, а Windows пишет вывод в кодировке системы.

    Без явного utf-8 первая же строка отчёта роняет шаг сборки — так и
    случилось на v1.2.1: exe собрался, а папка к раздаче не доехала.
    """
    console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)

    code = main(["--dist", str(built), "--package", str(tmp_path / "package")])

    assert code == 0
    console.flush()
    assert "LamodaItemFitter" in console.buffer.getvalue().decode("utf-8")
