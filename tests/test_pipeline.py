"""Сквозной прогон: очередь, потоки, раскладка файлов по папкам."""

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from app.core.compressor import Status
from app.core.jobs import collect
from app.core.settings import Settings
from app.pipeline import Pipeline


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


def run(jobs, settings, timeout: float = 180.0):
    """Гоняет очередь до конца, прокручивая цикл событий Qt."""
    import time

    pipeline = Pipeline()
    finished: list = []
    results: dict = {}
    pipeline.finished.connect(finished.append)
    pipeline.item_done.connect(lambda index, result: results.__setitem__(index, result))
    pipeline.start(jobs, settings)

    deadline = time.monotonic() + timeout
    while not finished and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)

    assert finished, "очередь не завершилась за отведённое время"
    return finished[0], results


def test_structure_is_reproduced_in_the_output_folder(qt_app, tree, tmp_path):
    out = tmp_path / "out"
    settings = Settings(
        output_dir=str(out), keep_structure=True, target_mb=0.25,
        max_side_enabled=True, max_side=1200,
    )
    summary, results = run(collect([tree]), settings)

    assert summary.errors == 0
    produced = sorted(
        path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file()
    )
    assert produced == [
        "shoot/cover.png",
        "shoot/dress_blue/back.jpg",
        "shoot/dress_blue/front.jpg",
        "shoot/dress_red/front.jpg",
    ]
    for result in results.values():
        if result.status in (Status.OK, Status.LOSSLESS, Status.COPIED):
            assert result.output_size <= settings.target_bytes


def test_flat_output_renames_colliding_files(qt_app, tree, tmp_path):
    out = tmp_path / "flat"
    settings = Settings(
        output_dir=str(out), keep_structure=False, target_mb=0.3, max_side=1200,
    )
    summary, _ = run(collect([tree]), settings)

    assert summary.errors == 0
    names = sorted(path.name for path in out.iterdir())
    # Два разных front.jpg должны ужиться в одной папке.
    assert names == ["back.jpg", "cover.png", "front.jpg", "front_1.jpg"]


def test_originals_survive_when_saving_next_to_them(qt_app, tree):
    before = {path: path.read_bytes() for path in tree.rglob("*.jpg")}
    settings = Settings(
        output_dir=str(tree), keep_structure=True, target_mb=0.2, max_side=900,
    )
    summary, _ = run(collect([tree]), settings)

    assert summary.errors == 0
    for path, content in before.items():
        assert path.read_bytes() == content, f"оригинал {path.name} изменился"


def test_summary_adds_up(qt_app, tree, tmp_path):
    settings = Settings(output_dir=str(tmp_path / "out"), target_mb=0.25, max_side=1000)
    jobs = collect([tree])
    summary, results = run(jobs, settings)

    assert summary.total == len(jobs)
    assert summary.processed == len(jobs)
    assert summary.output_bytes < summary.source_bytes
    assert len(results) == len(jobs)
