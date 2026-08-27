from pathlib import Path

from app.core.jobs import DestinationPlanner, Job, collect
from app.core.settings import CONFLICT_OVERWRITE, CONFLICT_SKIP, Settings


def test_collect_walks_folders_and_skips_non_images(tree):
    jobs = collect([tree])
    names = sorted(job.relative.as_posix() for job in jobs)
    assert names == [
        "shoot/cover.png",
        "shoot/dress_blue/back.jpg",
        "shoot/dress_blue/front.jpg",
        "shoot/dress_red/front.jpg",
    ]


def test_collect_deduplicates(tree):
    jobs = collect([tree, tree / "dress_blue", tree / "dress_blue" / "front.jpg"])
    assert len(jobs) == 4


def test_loose_file_lands_in_root(tree):
    job = collect([tree / "cover.png"])[0]
    assert job.relative == Path("cover.png")
    assert job.folder_label == ""


def test_planner_keeps_structure(tree, tmp_path):
    settings = Settings(output_dir=str(tmp_path / "out"), keep_structure=True)
    planner = DestinationPlanner(settings)
    job = Job(tree / "dress_blue" / "front.jpg", tree.parent)
    assert planner.reserve(job, ".jpg") == tmp_path / "out" / "shoot" / "dress_blue" / "front.jpg"


def test_planner_flattens_and_numbers_collisions(tree, tmp_path):
    settings = Settings(output_dir=str(tmp_path / "out"), keep_structure=False)
    planner = DestinationPlanner(settings)
    first = planner.reserve(Job(tree / "dress_blue" / "front.jpg", tree.parent), ".jpg")
    second = planner.reserve(Job(tree / "dress_red" / "front.jpg", tree.parent), ".jpg")
    assert first.name == "front.jpg"
    assert second.name == "front_1.jpg"


def test_planner_never_overwrites_the_source(tree):
    """Выгрузка в ту же папку не должна затирать оригиналы."""
    settings = Settings(
        output_dir=str(tree / "dress_blue"), keep_structure=False,
        on_conflict=CONFLICT_OVERWRITE,
    )
    planner = DestinationPlanner(settings)
    job = Job(tree / "dress_blue" / "front.jpg", tree / "dress_blue")
    destination = planner.reserve(job, ".jpg")
    assert destination != job.source
    assert destination.name == "front_1.jpg"


def test_planner_can_skip_existing(tree, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "cover.png").write_bytes(b"x")
    settings = Settings(output_dir=str(out), keep_structure=False, on_conflict=CONFLICT_SKIP)
    planner = DestinationPlanner(settings)
    assert planner.reserve(Job(tree / "cover.png", tree), ".png") is None


def test_planner_applies_suffix(tree, tmp_path):
    settings = Settings(
        output_dir=str(tmp_path / "out"), keep_structure=False, name_suffix="_lamoda"
    )
    planner = DestinationPlanner(settings)
    destination = planner.reserve(Job(tree / "cover.png", tree), ".png")
    assert destination.name == "cover_lamoda.png"
