"""Профили, связка сторон и сброс размеров."""

from app.core.settings import (
    ASPECT_BY_KEY,
    FIT_CONTAIN,
    Profiles,
    Settings,
    reset_size_fields,
)


def test_ratio_recomputes_the_other_side():
    settings = Settings(exact_width=2000, aspect_ratio="3:4")
    assert settings.resized_by_ratio("width") == (2000, 2667)

    settings.exact_height = 1500
    assert settings.resized_by_ratio("height") == (1125, 1500)


def test_free_ratio_leaves_both_sides_alone():
    settings = Settings(exact_width=2000, exact_height=2666, aspect_ratio="free")
    assert settings.resized_by_ratio("width") == (2000, 2666)


def test_every_ratio_has_both_orientations():
    """Список обязан быть симметричным: под вертикаль и под горизонталь."""
    pairs = {value for value in ASPECT_BY_KEY.values() if value}
    for wide, high in pairs:
        if wide != high:
            assert (high, wide) in pairs, f"нет пары для {wide}:{high}"


def test_exact_size_switches_off_the_side_limit():
    settings = Settings(exact_size_enabled=True, max_side_enabled=True, allow_downscale=True)
    normalized = settings.normalized()

    assert normalized.exact_size == (settings.exact_width, settings.exact_height)
    assert not normalized.max_side_enabled
    assert not normalized.allow_downscale


def test_lossless_mode_leaves_geometry_alone():
    settings = Settings(mode="lossless", exact_size_enabled=True, max_side_enabled=True)
    normalized = settings.normalized()

    assert not normalized.exact_size_enabled
    assert not normalized.max_side_enabled


def test_reset_returns_only_the_size_fields():
    settings = Settings(
        exact_width=999, exact_height=111, fit_mode=FIT_CONTAIN,
        quality=51, target_mb=1.5, output_dir="/tmp/somewhere",
    )

    reset_size_fields(settings)

    defaults = Settings()
    assert (settings.exact_width, settings.exact_height) == (
        defaults.exact_width, defaults.exact_height
    )
    assert settings.fit_mode == defaults.fit_mode
    # Всё, что не про размер, кнопка сброса не трогает.
    assert settings.quality == 51
    assert settings.target_mb == 1.5
    assert settings.output_dir == "/tmp/somewhere"


# ---------------------------------------------------------------------------
# Профили
# ---------------------------------------------------------------------------

def test_profile_survives_a_round_trip(tmp_path):
    profiles = Profiles(tmp_path / "profiles.json")
    settings = Settings(exact_size_enabled=True, exact_width=1080, exact_height=1350, quality=88)

    profiles.put("Инстаграм", settings)
    restored = Profiles(tmp_path / "profiles.json").get("Инстаграм")

    assert restored is not None
    assert restored.exact_size == (1080, 1350)
    assert restored.quality == 88


def test_profile_does_not_carry_the_output_folder(tmp_path):
    """Иначе, переслав профиль коллеге, вы утащите к нему свою папку."""
    profiles = Profiles(tmp_path / "profiles.json")
    profiles.put("Общий", Settings(output_dir="/home/me/выгрузка", theme="light"))

    restored = profiles.get("Общий")

    assert restored.output_dir == ""
    assert restored.theme == Settings().theme


def test_profiles_export_and_import(tmp_path):
    source = Profiles(tmp_path / "source.json")
    source.put("Квадрат", Settings(exact_width=1000, exact_height=1000))
    source.put("Вертикаль", Settings(exact_width=1000, exact_height=1500))
    shared = tmp_path / "shared.json"
    source.export_to(shared)

    target = Profiles(tmp_path / "target.json")
    added = target.import_from(shared)

    assert sorted(added) == ["Вертикаль", "Квадрат"]
    assert target.get("Квадрат").exact_width == 1000


def test_broken_profile_file_does_not_break_the_app(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text("это не json", encoding="utf-8")

    assert Profiles(path).names() == []


def test_missing_profile_file_is_fine(tmp_path):
    assert Profiles(tmp_path / "нет-такого.json").names() == []
