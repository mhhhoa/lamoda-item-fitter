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


def test_overwrite_does_not_eat_results_of_the_same_run(tree, tmp_path):
    """Перезапись касается старых файлов, а не того, что мы только что создали."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "front.jpg").write_text("старый файл", encoding="utf-8")
    settings = Settings(
        output_dir=str(out), keep_structure=False, on_conflict=CONFLICT_OVERWRITE
    )
    planner = DestinationPlanner(settings)

    first = planner.reserve(Job(tree / "dress_blue" / "front.jpg", tree.parent), ".jpg")
    second = planner.reserve(Job(tree / "dress_red" / "front.jpg", tree.parent), ".jpg")

    assert first.name == "front.jpg"  # старый файл перезаписать можно
    assert second.name == "front_1.jpg"  # а свежий результат — нельзя
    assert first != second


def test_planner_can_skip_existing(tree, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "cover.png").write_bytes(b"x")
    settings = Settings(output_dir=str(out), keep_structure=False, on_conflict=CONFLICT_SKIP)
    planner = DestinationPlanner(settings)
    assert planner.reserve(Job(tree / "cover.png", tree), ".png") is None


def test_planner_applies_suffix(tree, tmp_path):
    settings = Settings(
        output_dir=str(tmp_path / "out"), keep_structure=False, name_suffix="_web"
    )
    planner = DestinationPlanner(settings)
    destination = planner.reserve(Job(tree / "cover.png", tree), ".png")
    assert destination.name == "cover_web.png"


def _parse_version_info() -> dict[str, str]:
    """Разбирает version_info.txt так же, как это делает PyInstaller.

    Их загрузчик работает только на Windows, а формат — обычное выражение
    Python. Подставляем заглушки вместо классов и получаем ту же структуру:
    опечатка в файле здесь и всплывёт, а не через пять минут в сборке.
    """
    from pathlib import Path as FsPath

    class Node:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    names = (
        "VSVersionInfo", "FixedFileInfo", "StringFileInfo",
        "StringTable", "StringStruct", "VarFileInfo", "VarStruct",
    )
    source = (FsPath(__file__).resolve().parents[1] / "version_info.txt").read_text(
        encoding="utf-8"
    )
    info = eval(compile(source, "version_info.txt", "eval"), {n: Node for n in names})

    fields: dict[str, str] = {}
    numbers: dict[str, tuple] = {}

    def walk(node):
        if isinstance(node, Node):
            if len(node.args) == 2 and all(isinstance(a, str) for a in node.args):
                fields[node.args[0]] = node.args[1]
            numbers.update(
                {k: v for k, v in node.kwargs.items() if k in ("filevers", "prodvers")}
            )
            for value in (*node.args, *node.kwargs.values()):
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(info)
    fields.update({k: v for k, v in numbers.items()})
    return fields


def test_windows_version_info_is_valid_and_matches_the_package():
    """Свойства exe и app.__init__ должны расходиться только осознанно."""
    from app import APP_NAME, AUTHOR, AUTHOR_HANDLE, __version__

    fields = _parse_version_info()
    parts = [int(part) for part in __version__.split(".")]
    expected = tuple(parts + [0] * (4 - len(parts)))
    text = ".".join(str(part) for part in expected)

    assert fields["filevers"] == expected
    assert fields["prodvers"] == expected
    assert fields["FileVersion"] == text
    assert fields["ProductVersion"] == text
    assert fields["ProductName"] == APP_NAME
    assert fields["OriginalFilename"] == f"{APP_NAME.replace(' ', '')}.exe"
    assert AUTHOR in fields["CompanyName"] and AUTHOR_HANDLE in fields["CompanyName"]
    assert AUTHOR in fields["LegalCopyright"]
