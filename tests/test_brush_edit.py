"""Тесты ручной правки маски кистью.

Кисть нужна там, где автоматика ошиблась, поэтому проверяется главное:
закрашенное зелёным перестаёт осветляться как фон, закрашенное красным —
начинает. И что правка на кадре действительно видна, а не только в маске.
"""

import numpy as np
import pytest

from item_fitter import app


def _stroke(shape, box, colour) -> np.ndarray:
    """Слой редактора с одним мазком: RGBA, непрозрачный только в box."""
    layer = np.zeros((*shape, 4), dtype=np.uint8)
    y0, y1, x0, x1 = box
    layer[y0:y1, x0:x1, :3] = colour
    layer[y0:y1, x0:x1, 3] = 255
    return layer


GREEN = (22, 217, 90)
RED = (255, 59, 48)


@pytest.fixture
def prepared(scene):
    """Кадр, прогнанный через предпросмотр, и его состояние."""
    srgb, alpha_true = scene()
    image = np.round(srgb * 255).astype(np.uint8)
    pair, editor, md, dl, state = app.preview_one(
        image, "lamoda", "simple", 0.25, 1.0, 0.955, 2, "#FFFFFF"
    )
    return image, state, alpha_true


def test_stroke_is_applied_exactly_as_painted(prepared):
    """Внутри мазка маска обязана стать ровно такой, как закрасили.

    Смягчение границы не должно залезать внутрь: на тонком мазке это съедало
    половину правки, и она просто не срабатывала.
    """
    image, state, _ = prepared
    h, w = state["alpha"].shape
    box = (h // 2, h // 2 + 10, 8, 18)

    _, _, _, _, new_state = app.apply_mask_edit(
        {"layers": [_stroke((h, w), box, GREEN)]}, state
    )
    inside = new_state["alpha"][box[0] : box[1], box[2] : box[3]]
    assert inside.min() == 1.0, f"мазок размылся внутри: минимум {inside.min():.2f}"


def test_green_stroke_returns_area_to_product(prepared, scene):
    """Закрашенное зелёным перестаёт быть фоном и больше не осветляется."""
    image, state, _ = prepared
    h, w = state["alpha"].shape
    box = (h // 2, h // 2 + 14, 8, 24)  # заведомо чистый фон у левого края

    before = app._render(state["src"], state["alpha"], state["settings"])[0][1]
    assert before[box[0] : box[1], box[2] : box[3]].min() > 250, "тут и так должен быть белый фон"

    pair, _, md, _, new_state = app.apply_mask_edit(
        {"layers": [_stroke((h, w), box, GREEN)]}, state
    )
    assert new_state["alpha"][box[0] : box[1], box[2] : box[3]].min() > 0.9

    # Смотрим ровно тот кадр, который видит человек, а не пересобранный заново.
    after = pair[1]
    patch = after[box[0] + 4 : box[1] - 4, box[2] + 4 : box[3] - 4]
    assert patch.max() < 250, "закрашенное зелёным всё равно осталось выбеленным"


def test_red_stroke_sends_area_to_background(prepared):
    """Закрашенное красным становится фоном — даже посреди товара.

    Одного alpha=0 мало: пайплайн делит фон на модель освещённости, и кусок
    товара, помеченный фоном, вышел бы бледным пятном вместо белого.
    """
    image, state, _ = prepared
    alpha = state["alpha"]
    ys, xs = np.nonzero(alpha > 0.95)
    cy, cx = int(np.median(ys)), int(np.median(xs))
    box = (cy - 7, cy + 7, cx - 7, cx + 7)

    pair, _, _, _, new_state = app.apply_mask_edit(
        {"layers": [_stroke(alpha.shape, box, RED)]}, state
    )
    assert new_state["alpha"][box[0] : box[1], box[2] : box[3]].max() < 0.1
    assert new_state["force_bg"][box[0] : box[1], box[2] : box[3]].all()

    after = pair[1]
    patch = after[box[0] + 3 : box[1] - 3, box[2] + 3 : box[3] - 3]
    assert patch.min() > 200, "закрашенное красным не ушло в фон"


def test_reset_returns_to_automatic_mask(prepared):
    """Сброс возвращает маску, которую посчитала программа."""
    image, state, _ = prepared
    h, w = state["alpha"].shape
    _, _, _, _, edited = app.apply_mask_edit(
        {"layers": [_stroke((h, w), (h // 2, h // 2 + 12, 8, 22), GREEN)]}, state
    )
    assert not np.array_equal(edited["alpha"], edited["auto"])

    _, _, md, _, restored = app.reset_mask_edit(edited)
    assert np.array_equal(restored["alpha"], restored["auto"])
    assert "сброшена" in md.lower()


def test_edits_accumulate(prepared):
    """Второй мазок кладётся поверх первого, а не отменяет его."""
    image, state, _ = prepared
    h, w = state["alpha"].shape
    first = (h // 2, h // 2 + 12, 8, 20)
    second = (h // 2 + 20, h // 2 + 32, 8, 20)

    _, _, _, _, s1 = app.apply_mask_edit({"layers": [_stroke((h, w), first, GREEN)]}, state)
    _, _, _, _, s2 = app.apply_mask_edit({"layers": [_stroke((h, w), second, GREEN)]}, s1)

    assert s2["alpha"][first[0] : first[1], first[2] : first[3]].min() > 0.9
    assert s2["alpha"][second[0] : second[1], second[2] : second[3]].min() > 0.9


def test_layer_is_rescaled_to_frame(prepared):
    """Редактор может отдать мазок в размере отображения — его надо привести к кадру."""
    image, state, _ = prepared
    h, w = state["alpha"].shape
    small = (h // 2, w // 2)
    box = (small[0] // 2, small[0] // 2 + 8, 4, 12)

    _, _, _, _, new_state = app.apply_mask_edit(
        {"layers": [_stroke(small, box, GREEN)]}, state
    )
    assert new_state["alpha"].shape == (h, w)
    assert new_state["alpha"].max() > 0.9


def test_empty_strokes_are_rejected_clearly(prepared):
    """Нажатие «Применить» без мазков должно объяснять, а не молчать."""
    image, state, _ = prepared
    with pytest.raises(Exception) as exc:
        app.apply_mask_edit({"layers": []}, state)
    assert "закрасьте" in str(exc.value).lower()


def test_report_is_not_inside_the_archive(scene, tmp_path):
    """Архив уходит на маркетплейс как есть — служебному отчёту там не место."""
    import zipfile

    from item_fitter.colorspace import save_jpeg

    src = tmp_path / "in"
    src.mkdir()
    for i in range(2):
        img, _ = scene()
        save_jpeg(src / f"art{i}.jpg", img, quality=96)

    summary, rows, gallery, zip_upd, report_upd = app.run_batch_ui(
        None, str(src), "lamoda", "simple", 0.25, 1.0, 0.955, 2, "#FFFFFF"
    )

    archive = zip_upd["value"]
    names = zipfile.ZipFile(archive).namelist()
    assert len(names) == 2, f"в архиве лишние файлы: {names}"
    assert not any(n.lower().endswith(".html") for n in names), f"отчёт попал в архив: {names}"

    # Отчёт при этом доступен отдельной кнопкой.
    from pathlib import Path

    assert Path(report_upd["value"]).exists()
    assert report_upd["interactive"] is True
    assert zip_upd["interactive"] is True
