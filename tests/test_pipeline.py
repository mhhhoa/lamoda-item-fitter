"""Интеграционные тесты: пайплайн целиком, пакетный прогон, экспорт."""

import numpy as np
import pytest
from PIL import Image

from item_fitter import batch, config, pipeline, report
from item_fitter.colorspace import save_jpeg
from item_fitter.qa import FAIL, OK


def test_pipeline_produces_white_background(scene, fast_settings):
    """Сквозной прогон: вердикт чистый, фон белый, товар цел."""
    srgb, _ = scene()
    res = pipeline.process_array(srgb, fast_settings)

    assert res.verdict == OK, res.report.notes
    assert res.report.metrics["bg_corner_min"] == 255
    assert res.report.metrics["product_delta_e"] < fast_settings.max_product_delta_e
    assert res.image.shape == srgb.shape


def test_written_file_really_has_white_corners(scene, fast_settings, tmp_path):
    """Белизну обещаем не в памяти, а в отгружаемом файле."""
    srgb, _ = scene()
    src = tmp_path / "in.jpg"
    save_jpeg(src, srgb, quality=96)

    dst = tmp_path / "out.jpg"
    pipeline.process_file(src, dst, fast_settings)

    written = np.asarray(Image.open(dst).convert("RGB"))
    h, w, _ = written.shape
    p = 24
    corners = [written[:p, :p], written[:p, w - p :], written[h - p :, :p], written[h - p :, w - p :]]
    assert min(int(c.min()) for c in corners) == 255


def test_reflection_survives_full_pipeline(scene, fast_settings):
    """Отражение обязано остаться видимым — иначе товар «висит в воздухе»."""
    srgb, _ = scene()
    res = pipeline.process_array(srgb, fast_settings)

    m = res.report.metrics
    assert m["reflection_before"] > 0.005, "в исходнике отражения не было — тест бессмысленен"
    assert m["reflection_after"] > m["reflection_before"] * 0.5


def test_colour_cast_correction_has_a_working_strength(scene):
    """Снятие рефлекса обязано уметь приблизить товар к его истинному цвету.

    Проверяется не одно фиксированное значение, а наличие рабочего: сила коррекции
    должна соответствовать доле цветного света в освещении сцены. Поставить её
    «на глаз» нельзя — для того и существует `fitter calibrate`, который подбирает
    её по эталонным парам.
    """
    true_product = (0.62, 0.33, 0.05)
    spill = 0.18
    srgb, alpha = scene(bg=(0.80, 0.90, 0.70), product=true_product, spill=spill)

    from item_fitter.colorspace import delta_e_2000, linear_to_srgb, rgb_to_lab

    target = rgb_to_lab(linear_to_srgb(np.asarray(true_product, np.float32)))
    core = alpha > 0.99

    def drift(strength: float) -> float:
        res = pipeline.process_array(
            srgb, config.Settings(matting="simple", wb_strength=strength)
        )
        return float(delta_e_2000(rgb_to_lab(res.image[core]), target).mean())

    baseline = drift(0.0)
    matched = drift(spill)
    assert matched < baseline, (
        f"коррекция на подходящей силе не приблизила цвет к истинному: "
        f"{baseline:.2f} -> {matched:.2f}"
    )


def test_colour_cast_overcorrection_is_worse(scene):
    """Коррекция на полную силу при слабом рефлексе обязана ухудшать цвет.

    Это не дефект, а причина, по которой сила вынесена в настройку и по умолчанию
    выставлена консервативно: снять оттенка больше, чем его было, — значит
    перекрасить товар.
    """
    true_product = (0.62, 0.33, 0.05)
    srgb, alpha = scene(bg=(0.80, 0.90, 0.70), product=true_product, spill=0.18)

    from item_fitter.colorspace import delta_e_2000, linear_to_srgb, rgb_to_lab

    target = rgb_to_lab(linear_to_srgb(np.asarray(true_product, np.float32)))
    core = alpha > 0.99

    def drift(strength: float) -> float:
        res = pipeline.process_array(
            srgb, config.Settings(matting="simple", wb_strength=strength)
        )
        return float(delta_e_2000(rgb_to_lab(res.image[core]), target).mean())

    assert drift(1.0) > drift(0.18)


def test_target_background_can_be_grey(scene):
    """Часть категорий требует светло-серый фон, а не чисто белый."""
    srgb, _ = scene()
    res = pipeline.process_array(srgb, config.Settings(matting="simple", target_bg="#EFEFEF"))
    corner = int(round(float(res.image[0, 0].min()) * 255))
    assert corner == pytest.approx(239, abs=2)


def test_geometry_fit_never_crops_product(scene):
    """Режим fit обязан вписывать кадр целиком, добивая полями."""
    srgb, _ = scene(h=400, w=300)
    settings = config.Settings(
        matting="simple", geometry_mode="fit", out_width=1500, out_height=2000
    )
    res = pipeline.process_array(srgb, settings)
    assert res.image.shape[:2] == (2000, 1500)


def test_batch_survives_a_broken_file(scene, fast_settings, tmp_path):
    """Один битый файл не должен ронять пакет из 350 кадров."""
    src = tmp_path / "in"
    src.mkdir()
    for i in range(2):
        img, _ = scene()
        save_jpeg(src / f"art{i}.jpg", img, quality=96)
    (src / "broken.jpg").write_bytes(b"not an image at all")

    seen: list[tuple] = []
    results = batch.run_batch(
        src, tmp_path / "out", fast_settings, progress=lambda *a: seen.append(a)
    )

    assert len(results) == 2, "хорошие кадры должны обработаться"
    assert len(seen) == 3, "битый файл должен быть отмечен, а не пропущен молча"
    assert any(a[4] is not None for a in seen), "ошибка должна дойти до отчёта"


def test_report_is_self_contained(scene, fast_settings, tmp_path):
    """Отчёт должен быть одним файлом: превью внутри, ничего не прикладывать."""
    srgb, _ = scene()
    src = tmp_path / "a.jpg"
    save_jpeg(src, srgb, quality=96)
    res = pipeline.process_file(src, tmp_path / "out" / "a.jpg", fast_settings)

    path = report.write_report(tmp_path / "r.html", [res], preset_name="lamoda")
    html = path.read_text(encoding="utf-8")

    assert "data:image/jpeg;base64," in html
    assert "<img src='/" not in html and '<img src="/' not in html
    assert "Отчёт по замене фона" in html


def test_jpeg_respects_size_limit(scene, tmp_path):
    """Файл обязан влезать в лимит маркетплейса, иначе загрузка отвалится."""
    srgb, _ = scene(h=1200, w=900)
    limit = 60_000
    size = save_jpeg(tmp_path / "x.jpg", srgb, quality=98, max_bytes=limit)
    assert size <= limit


def test_presets_all_load():
    """Любой пресет в репозитории обязан читаться — иначе интерфейс упадёт при старте."""
    names = config.list_presets()
    assert names, "пресеты не найдены"
    for name in names:
        assert isinstance(config.load_preset(name), config.Settings)


def test_unknown_preset_key_is_rejected(tmp_path):
    """Опечатка в YAML должна ловиться сразу, а не молча игнорироваться."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("wb_strenght: 0.5\n", encoding="utf-8")  # опечатка в имени
    with pytest.raises(ValueError, match="Неизвестные параметры"):
        config.load_preset(bad)


def test_busy_background_is_flagged_not_silently_ruined():
    """Сюжетный кадр не должен обрабатываться молча — он обязан попасть в отчёт."""
    rng = np.random.default_rng(0)
    noisy = rng.random((300, 240, 3)).astype(np.float32)  # фон без всякой гладкости
    res = pipeline.process_array(noisy, config.Settings(matting="simple"))

    assert res.verdict != OK
    assert res.report.notes


def test_full_frame_object_reports_failure(scene):
    """Если чистого фона не осталось, это ошибка, а не тихий мусор на выходе."""
    flat = np.full((200, 150, 3), 0.35, dtype=np.float32)
    res = pipeline.process_array(flat, config.Settings(matting="simple"))
    assert res.verdict in (FAIL, "CHECK")
    assert res.report.notes
