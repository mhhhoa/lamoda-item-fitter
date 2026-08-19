"""Куда что сохраняется и что происходит при совпадении имён."""

import numpy as np
import pytest
from PIL import Image

from lamoda_item_fitter.batch import (
    COPY, OVERWRITE, SKIP, apply_policy, conflicts, plan, process_one,
)
from lamoda_item_fitter.fitter import FITTED
from tests.conftest import canvas


@pytest.fixture
def photo(tmp_path):
    def make(path):
        array = canvas(900, 1400)
        array[500:700, 200:1100] = 60
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(array).save(path)
        return path
    return make


def test_files_land_in_the_output_root(tmp_path, preset, photo):
    source = photo(tmp_path / "src" / "ботинок.jpg")

    jobs = plan([source], preset, output_root=tmp_path / "out")

    assert len(jobs) == 1
    assert jobs[0].destination == tmp_path / "out" / "ботинок_lamodafit.jpg"


def test_folder_keeps_its_name_and_nesting(tmp_path, preset, photo):
    photo(tmp_path / "Артикул 42" / "первое.jpg")
    photo(tmp_path / "Артикул 42" / "детали" / "второе.png")

    jobs = plan([tmp_path / "Артикул 42"], preset, output_root=tmp_path / "out")
    relatives = sorted(str(job.relative) for job in jobs)

    assert relatives == [
        "Артикул 42/детали/второе_lamodafit.jpg",
        "Артикул 42/первое_lamodafit.jpg",
    ]


def test_folder_suffix_is_optional(tmp_path, preset, photo):
    photo(tmp_path / "Артикул 42" / "первое.jpg")
    with_suffix = preset.replace(
        output=preset.output.__class__(**{**preset.output.__dict__, "suffix_on_folder": True}))

    jobs = plan([tmp_path / "Артикул 42"], with_suffix, output_root=tmp_path / "out")

    assert str(jobs[0].relative).startswith("Артикул 42_lamodafit/")


def test_png_output_changes_the_extension(tmp_path, preset, photo):
    source = photo(tmp_path / "src" / "ботинок.jpg")
    as_png = preset.replace(
        output=preset.output.__class__(**{**preset.output.__dict__, "format": "png"}))

    jobs = plan([source], as_png, output_root=tmp_path / "out")

    assert jobs[0].destination.name == "ботинок_lamodafit.png"


def _existing(tmp_path, preset, photo):
    source = photo(tmp_path / "src" / "ботинок.jpg")
    jobs = plan([source], preset, output_root=tmp_path / "out")
    jobs[0].destination.parent.mkdir(parents=True, exist_ok=True)
    jobs[0].destination.write_text("старый файл", encoding="utf-8")
    return jobs


def test_conflicts_are_detected(tmp_path, preset, photo):
    jobs = _existing(tmp_path, preset, photo)

    assert conflicts(jobs) == jobs


def test_copy_policy_keeps_both_files(tmp_path, preset, photo):
    jobs = _existing(tmp_path, preset, photo)

    accepted, skipped = apply_policy(jobs, COPY)

    assert accepted[0].destination.name == "ботинок_lamodafit (2).jpg"
    assert not skipped


def test_overwrite_policy_reuses_the_path(tmp_path, preset, photo):
    jobs = _existing(tmp_path, preset, photo)

    accepted, skipped = apply_policy(jobs, OVERWRITE)

    assert accepted[0].destination == jobs[0].destination
    assert not skipped


def test_skip_policy_leaves_the_file_alone(tmp_path, preset, photo):
    jobs = _existing(tmp_path, preset, photo)

    accepted, skipped = apply_policy(jobs, SKIP)

    assert not accepted
    assert skipped == jobs


def test_same_names_inside_one_batch_do_not_collide(tmp_path, preset, photo):
    photo(tmp_path / "a" / "фото.jpg")
    photo(tmp_path / "b" / "фото.jpg")

    jobs = plan([tmp_path / "a" / "фото.jpg", tmp_path / "b" / "фото.jpg"],
                preset, output_root=tmp_path / "out")
    accepted, _ = apply_policy(jobs, OVERWRITE)

    assert len({job.destination for job in accepted}) == 2


def test_processing_writes_a_correct_file(tmp_path, preset, photo):
    source = photo(tmp_path / "src" / "ботинок.jpg")
    jobs = plan([source], preset, output_root=tmp_path / "out")

    outcome = process_one(jobs[0], preset)

    assert outcome.status == FITTED
    assert outcome.job.destination.exists()
    assert outcome.size_bytes <= preset.output.max_bytes
    with Image.open(outcome.job.destination) as written:
        assert written.size == (preset.canvas.width, preset.canvas.height)


def test_unreadable_file_is_reported_not_raised(tmp_path, preset):
    from lamoda_item_fitter.batch import FAILED, Job
    from pathlib import Path

    broken = tmp_path / "битый.jpg"
    broken.write_bytes(b"not an image")
    job = Job(broken, tmp_path / "out" / "битый_lamodafit.jpg", Path("битый_lamodafit.jpg"))

    outcome = process_one(job, preset)

    assert outcome.status == FAILED
    assert "не удалось открыть" in outcome.reason
