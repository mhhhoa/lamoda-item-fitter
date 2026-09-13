"""Визуальный интерфейс: локальная страница в браузере.

Рассчитан на работу без командной строки — открыть, перетащить кадры, забрать
результат. Тот же самый интерфейс поднимается для коллег по локальной сети:
достаточно запустить с --host 0.0.0.0.
"""

from __future__ import annotations

import inspect
import socket
import tempfile
import zipfile
from pathlib import Path

from scipy import ndimage

import gradio as gr
import numpy as np
import yaml

from . import report as repmod
from .batch import SUPPORTED_SUFFIXES, find_images
from .config import PRESET_DIR, Settings, list_presets, load_preset
from .matting import available_backends, get_backend
from .colorspace import hex_to_rgb, load_srgb, save_jpeg
from .pipeline import process_array, process_file
from .qa import CHECK, FAIL, OK

_BADGE = {OK: "готово", CHECK: "проверить", FAIL: "ошибка"}

# Gradio 6 перенёс тему из конструктора Blocks в launch(). На машине пользователя
# может оказаться любая из версий, поэтому определяем адресата один раз здесь.
_GRADIO_MAJOR = int(gr.__version__.split(".")[0])

_INTRO = """
# Замена фона на белый

Фон уходит в чистый белый, **отражение под товаром сохраняется**, цветной рефлекс
с кожи и ткани снимается, а сам товар не меняется ни на пиксель.
"""


def _workdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="fitter_"))


def _build_archive(out_dir: Path, archive: Path) -> Path:
    """Пересобирает архив из готовых кадров. Отчёт внутрь не попадает."""
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(out_dir))
    return archive


def _collect_inputs(files, folder: str) -> tuple[list[Path], Path | None]:
    """Собирает пути к кадрам: либо перетащенные файлы, либо путь к папке."""
    if folder and folder.strip():
        root = Path(folder.strip().strip('"').strip("'")).expanduser()
        return find_images(root), root
    if not files:
        return [], None
    paths = [Path(f if isinstance(f, str) else f.name) for f in files]
    return [p for p in paths if p.suffix.lower() in SUPPORTED_SUFFIXES], None


def _settings_from_ui(preset, matting, wb, reflection, knee_low, degree, target_bg) -> Settings:
    return load_preset(preset).replace(
        matting=matting,
        wb_strength=float(wb),
        reflection_strength=float(reflection),
        knee_low=float(knee_low),
        poly_degree=int(degree),
        target_bg=target_bg,
    )


# --- вкладка 1: пакет -------------------------------------------------------


def run_batch_ui(
    files, folder, preset, matting, wb, reflection, knee_low, degree, target_bg,
    progress=gr.Progress(),
):
    paths, root = _collect_inputs(files, folder)
    if not paths:
        raise gr.Error("Не выбрано ни одного изображения. Перетащите файлы или укажите папку.")

    settings = _settings_from_ui(preset, matting, wb, reflection, knee_low, degree, target_bg)
    work = _workdir()
    out_dir = work / "готово"
    out_dir.mkdir(parents=True, exist_ok=True)

    masks_dir = work / "маски"
    masks_dir.mkdir(parents=True, exist_ok=True)

    matte_fn = get_backend(settings.matting)
    results, failures, rows, gallery, items = [], [], [], [], []

    for src in progress.tqdm(paths, desc="Обработка"):
        rel = src.relative_to(root) if root and src.is_relative_to(root) else Path(src.name)
        dst = out_dir / rel.with_suffix(".jpg")
        try:
            res = process_file(src, dst, settings, matte_fn=matte_fn)
            results.append(res)
            m = res.report.metrics
            rows.append(
                [
                    src.name,
                    _BADGE[res.verdict],
                    m.get("bg_corner_min"),
                    m.get("product_delta_e"),
                    m.get("file_kb"),
                    "; ".join(res.report.notes) or "—",
                ]
            )
            gallery.append((res.image, f"{src.name} · {_BADGE[res.verdict]}"))

            # Маска кладётся на диск, чтобы её можно было поправить кистью сразу
            # после прогона, не пересчитывая нейросеть.
            from PIL import Image as _Image

            mask_path = masks_dir / f"{len(items):04d}.png"
            _Image.fromarray(
                np.round(np.clip(res.alpha, 0, 1) * 255).astype(np.uint8), "L"
            ).save(mask_path)
            items.append({"name": src.name, "src": str(src), "dst": str(dst),
                          "mask": str(mask_path)})
        except Exception as exc:  # noqa: BLE001
            failures.append((src, exc))
            rows.append([src.name, "ошибка", None, None, None, str(exc)[:200]])

    # Отчёт кладётся РЯДОМ с папкой результатов, а не внутрь неё: в архив для
    # маркетплейса он попадать не должен, его забирают отдельной кнопкой.
    report_path = work / "отчёт.html"
    repmod.write_report(report_path, results, failures, preset_name=preset)

    archive = _build_archive(out_dir, work / "результат.zip")

    tally = {v: sum(1 for r in results if r.verdict == v) for v in (OK, CHECK, FAIL)}
    summary = (
        f"### Обработано: {len(results)} из {len(paths)}\n\n"
        f"- готово без замечаний: **{tally[OK]}**\n"
        f"- проверить глазами: **{tally[CHECK]}**\n"
        f"- ошибки: **{tally[FAIL] + len(failures)}**\n\n"
        f"Смотреть глазами нужно только помеченные строки."
    )
    batch = {
        "items": items,
        "out_dir": str(out_dir),
        "archive": str(archive),
        "settings": settings,
    }
    return (
        summary,
        rows,
        gallery,
        gr.update(value=str(archive), interactive=True),
        gr.update(value=str(report_path), interactive=True),
        batch,
    )


# --- вкладка 2: один кадр и правка маски ------------------------------------


def _overlay(srgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Кадр с подсветкой того, что программа сочла товаром.

    Без подсветки править маску вслепую: на самом кадре не видно, где именно
    программа ошиблась.
    """
    tint = np.array([0.15, 0.85, 0.45], dtype=np.float32)
    a = np.clip(alpha, 0.0, 1.0)[..., None] * 0.3
    mixed = np.clip(srgb, 0, 1) * (1 - a) + tint * a
    return np.round(np.clip(mixed, 0, 1) * 255).astype(np.uint8)


# Холст редактора в полном разрешении тормозит браузер на каждом штрихе.
# Мазки всё равно приводятся к размеру кадра при применении, поэтому показывать
# уменьшенную копию безопасно.
_EDITOR_MAX_SIDE = 1100


def _editor_value(srgb: np.ndarray, alpha: np.ndarray) -> dict:
    overlay = _overlay(srgb, alpha)
    h, w = overlay.shape[:2]
    scale = _EDITOR_MAX_SIDE / max(h, w)
    if scale < 1.0:
        from PIL import Image

        overlay = np.asarray(
            Image.fromarray(overlay).resize(
                (max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS
            )
        )
    return {"background": overlay, "layers": [], "composite": None}


def _render(
    srgb: np.ndarray,
    alpha: np.ndarray,
    settings: Settings,
    force_bg: np.ndarray | None = None,
):
    """Собирает кадр по готовой маске и готовит всё, что показывает вкладка.

    force_bg — области, которые человек вручную пометил как фон. Их недостаточно
    просто исключить из маски: пайплайн делит фон на модель освещённости, и кусок
    товара, помеченный фоном, превратился бы в бледное пятно, а не в белый фон.
    Раз пометка ручная и однозначная, такие места закрашиваются целевым цветом
    фона напрямую.
    """
    return _present(srgb, process_array(srgb, settings, alpha=alpha), settings, force_bg)


def _present(srgb, res, settings: Settings, force_bg: np.ndarray | None = None):
    """Готовит всё, что показывает вкладка, по уже посчитанному результату.

    Отделено от _render, потому что предпросмотр уже имеет результат на руках:
    раньше он считал кадр второй раз только чтобы его показать.
    """
    if force_bg is not None and force_bg.any():
        target = np.asarray(hex_to_rgb(settings.target_bg), dtype=np.float32) / 255.0
        soft = ndimage.gaussian_filter(force_bg.astype(np.float32), 1.0)[..., None]
        res.image = np.clip(res.image * (1 - soft) + target * soft, 0, 1).astype(np.float32)

    m = res.report.metrics

    lines = [
        f"**Вердикт: {_BADGE[res.verdict]}**",
        "",
        f"- фон в углах: `{m.get('bg_corner_min')}` из 255",
        f"- сдвиг цвета товара: `ΔE2000 {m.get('product_delta_e')}` "
        f"(меньше 1 — глазом не видно)",
        f"- площадь отражения: `{m.get('reflection_before')}` → `{m.get('reflection_after')}`",
        f"- выбелено товара: `{m.get('blown_ratio')}`",
        f"- время: `{res.timing['total']:.1f} с`",
    ]
    if res.report.notes:
        lines += ["", "**На что обратить внимание:**"] + [f"- {n}" for n in res.report.notes]

    before8 = np.round(np.clip(srgb, 0, 1) * 255).astype(np.uint8)
    after8 = np.round(np.clip(res.image, 0, 1) * 255).astype(np.uint8)

    saved = _workdir() / "кадр.jpg"
    save_jpeg(saved, res.image, quality=settings.jpeg_quality, max_bytes=settings.max_bytes)

    return (before8, after8), _editor_value(srgb, res.alpha), "\n".join(lines), str(saved)


def preview_one(image, preset, matting, wb, reflection, knee_low, degree, target_bg):
    if image is None:
        raise gr.Error("Загрузите один кадр.")

    srgb = np.asarray(image, dtype=np.float32) / 255.0
    settings = _settings_from_ui(preset, matting, wb, reflection, knee_low, degree, target_bg)
    res = process_array(srgb, settings)

    empty = np.zeros(res.alpha.shape, dtype=bool)
    pair, editor, md, saved = _present(srgb, res, settings)
    state = {
        "src": srgb,
        "auto": res.alpha,
        "alpha": res.alpha,
        "force_bg": empty,
        "settings": settings,
    }
    return pair, editor, md, gr.update(value=saved, interactive=True), state


def _strokes_to_masks(layers, shape) -> tuple[np.ndarray, np.ndarray]:
    """Разбирает мазки на «вернуть товару» (зелёное) и «отправить в фон» (красное)."""
    add = np.zeros(shape, dtype=bool)
    remove = np.zeros(shape, dtype=bool)

    for layer in layers or []:
        arr = np.asarray(layer)
        if arr.ndim != 3 or arr.shape[-1] < 4:
            continue
        if arr.shape[:2] != shape:
            # Редактор может отдать слой в размере отображения, а не оригинала.
            from PIL import Image

            arr = np.asarray(
                Image.fromarray(arr.astype(np.uint8), "RGBA").resize(
                    (shape[1], shape[0]), Image.NEAREST
                )
            )
        painted = arr[..., 3] > 8
        rgb = arr[..., :3].astype(np.int16)
        add |= painted & (rgb[..., 1] > rgb[..., 0] + 40) & (rgb[..., 1] > rgb[..., 2] + 40)
        remove |= painted & (rgb[..., 0] > rgb[..., 1] + 40) & (rgb[..., 0] > rgb[..., 2] + 40)

    return add, remove


def _apply_strokes(editor_value, state):
    """Переносит мазки на маску. Возвращает (маска, ручной фон, сколько добавили, сколько убрали)."""
    if not state:
        raise gr.Error("Сначала выберите кадр.")
    if not isinstance(editor_value, dict):
        raise gr.Error("Нечего применять — сначала закрасьте нужные места.")

    alpha = state["alpha"].copy()
    add, remove = _strokes_to_masks(editor_value.get("layers"), alpha.shape)
    if not add.any() and not remove.any():
        raise gr.Error("Мазков не найдено. Закрасьте зелёным товар или красным фон.")

    alpha[add] = 1.0
    alpha[remove] = 0.0

    force_bg = state.get("force_bg")
    if force_bg is None:
        force_bg = np.zeros(alpha.shape, dtype=bool)
    force_bg = (force_bg | remove) & ~add

    # Граница мазка иначе получается ступенькой там, где закрашенный товар
    # соприкасается с фоном. Смягчается только полоса СНАРУЖИ мазка: внутри
    # должно остаться ровно то, что человек закрасил, иначе тонкий мазок
    # размывается наполовину и правка не срабатывает.
    painted = add | remove
    outside = ndimage.binary_dilation(painted, iterations=2) & ~painted
    if outside.any():
        alpha = np.where(outside, ndimage.gaussian_filter(alpha, 1.0), alpha)

    return alpha, force_bg, int(add.sum()), int(remove.sum())


def _edit_note(added: int, removed: int) -> str:
    return f"Правка применена: {added} точек вернули товару, {removed} отправили в фон.\n\n"


def apply_mask_edit(editor_value, state):
    alpha, force_bg, added, removed = _apply_strokes(editor_value, state)
    pair, editor, md, saved = _render(state["src"], alpha, state["settings"], force_bg)
    state = {**state, "alpha": alpha, "force_bg": force_bg}
    return pair, editor, _edit_note(added, removed) + md, gr.update(value=saved, interactive=True), state


# --- правка кадра прямо из результатов пакета --------------------------------


def pick_from_batch(batch, evt: gr.SelectData):
    """Открывает выбранный в галерее кадр в редакторе маски."""
    if not batch or not batch.get("items"):
        raise gr.Error("Сначала обработайте пакет.")
    if evt.index is None or evt.index >= len(batch["items"]):
        raise gr.Error("Этот кадр обработать не удалось — править нечего.")

    from PIL import Image

    item = batch["items"][evt.index]
    srgb, _ = load_srgb(item["src"])
    alpha = np.asarray(Image.open(item["mask"]).convert("L"), dtype=np.float32) / 255.0
    settings = batch["settings"]

    pair, editor, md, _ = _render(srgb, alpha, settings)
    state = {
        "src": srgb,
        "auto": alpha,
        "alpha": alpha,
        "force_bg": np.zeros(alpha.shape, dtype=bool),
        "settings": settings,
        "item": item,
        "batch": batch,
    }
    return (
        gr.update(visible=True),
        f"### Правим: {item['name']}",
        pair,
        editor,
        md,
        state,
    )


def _save_batch_frame(state, alpha, force_bg):
    """Пересобирает кадр, перезаписывает файл в папке результата и архив."""
    item, batch = state["item"], state["batch"]
    settings = state["settings"]

    pair, editor, md, _ = _render(state["src"], alpha, settings, force_bg)
    res = process_array(state["src"], settings, alpha=alpha)
    image = res.image
    if force_bg is not None and force_bg.any():
        target = np.asarray(hex_to_rgb(settings.target_bg), dtype=np.float32) / 255.0
        soft = ndimage.gaussian_filter(force_bg.astype(np.float32), 1.0)[..., None]
        image = np.clip(image * (1 - soft) + target * soft, 0, 1).astype(np.float32)

    save_jpeg(item["dst"], image, quality=settings.jpeg_quality, max_bytes=settings.max_bytes)
    _build_archive(Path(batch["out_dir"]), Path(batch["archive"]))
    return pair, editor, md


def apply_batch_edit(editor_value, state):
    alpha, force_bg, added, removed = _apply_strokes(editor_value, state)
    pair, editor, md = _save_batch_frame(state, alpha, force_bg)
    state = {**state, "alpha": alpha, "force_bg": force_bg}
    note = _edit_note(added, removed) + "Файл в папке результата и архив обновлены.\n\n"
    return pair, editor, note + md, gr.update(value=state["batch"]["archive"]), state


def reset_batch_edit(state):
    if not state or "item" not in state:
        raise gr.Error("Сначала выберите кадр в галерее.")
    empty = np.zeros(state["auto"].shape, dtype=bool)
    pair, editor, md = _save_batch_frame(state, state["auto"], empty)
    state = {**state, "alpha": state["auto"], "force_bg": empty}
    return pair, editor, "Правка сброшена.\n\n" + md, gr.update(value=state["batch"]["archive"]), state


def reset_mask_edit(state):
    if not state:
        raise gr.Error("Сначала нажмите «Показать результат».")
    pair, editor, md, saved = _render(state["src"], state["auto"], state["settings"])
    state = {
        **state,
        "alpha": state["auto"],
        "force_bg": np.zeros(state["auto"].shape, dtype=bool),
    }
    return pair, editor, "Правка сброшена.\n\n" + md, gr.update(value=saved), state


def save_preset_ui(name, preset, matting, wb, reflection, knee_low, degree, target_bg):
    name = (name or "").strip()
    if not name:
        raise gr.Error("Впишите имя пресета.")
    safe = "".join(c for c in name if c.isalnum() or c in "-_")
    if not safe:
        raise gr.Error("Имя пресета должно содержать буквы или цифры.")

    settings = _settings_from_ui(preset, matting, wb, reflection, knee_low, degree, target_bg)
    path = PRESET_DIR / f"{safe}.yaml"
    path.write_text(
        yaml.safe_dump(settings.to_dict(), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return f"Пресет сохранён: `{path}`. Он появится в списке после перезапуска."


# --- сборка интерфейса ------------------------------------------------------


def build() -> gr.Blocks:
    presets = list_presets() or ["lamoda"]
    default = "lamoda" if "lamoda" in presets else presets[0]
    base = load_preset(default)

    blocks_kwargs = {"title": "Замена фона на белый"}
    if _GRADIO_MAJOR < 6:
        blocks_kwargs["theme"] = gr.themes.Soft()

    with gr.Blocks(**blocks_kwargs) as demo:
        gr.Markdown(_INTRO)

        with gr.Row():
            preset = gr.Dropdown(presets, value=default, label="Пресет", scale=2)
            matting = gr.Dropdown(
                available_backends(), value=base.matting, label="Матирование", scale=2
            )
            target_bg = gr.Textbox(base.target_bg, label="Цвет фона", scale=1)

        with gr.Accordion("Тонкая настройка", open=False):
            with gr.Row():
                wb = gr.Slider(
                    0, 1, base.wb_strength, step=0.05,
                    label="Снятие цветного рефлекса с товара",
                    info="Насколько убирать подкраску фоном с кожи и ткани.",
                )
                reflection = gr.Slider(
                    0, 1, base.reflection_strength, step=0.05,
                    label="Сила отражения",
                    info="1 — как в оригинале. 0 — убрать тень совсем.",
                )
            with gr.Row():
                knee_low = gr.Slider(
                    0.95, 0.999, base.knee_low, step=0.001,
                    label="Порог дотяжки белого",
                    info="Ниже — фон белее, но светлая кожа и белый реквизит начинают выбеливаться.",
                )
                degree = gr.Slider(
                    1, 3, base.poly_degree, step=1,
                    label="Степень модели фона",
                    info="2 — обычная циклорама. 3 — сложный градиент или виньетка.",
                )

        controls = [preset, matting, wb, reflection, knee_low, degree, target_bg]

        with gr.Tab("Пакет"):
            gr.Markdown("Перетащите кадры **или** впишите путь к папке на этом компьютере.")
            files = gr.File(
                file_count="multiple", label="Кадры", file_types=["image"], height=160
            )
            folder = gr.Textbox(
                label="…либо путь к папке",
                placeholder=r"C:\Съёмки\неделя_42  (если заполнено — файлы выше игнорируются)",
            )
            run_btn = gr.Button("Обработать всё", variant="primary", size="lg")
            summary = gr.Markdown()
            table = gr.Dataframe(
                headers=["файл", "статус", "углы", "ΔE товара", "КБ", "замечания"],
                label="Результаты",
                wrap=True,
            )
            gallery = gr.Gallery(label="Результат — нажмите на кадр, чтобы поправить маску",
                                 columns=4, height=340)
            with gr.Row():
                zip_btn = gr.DownloadButton(
                    "Скачать архив с готовыми кадрами", variant="primary", interactive=False
                )
                report_btn = gr.DownloadButton("Скачать HTML-отчёт", interactive=False)
            gr.Markdown(
                "Отчёт скачивается отдельно и в архив не кладётся — архив уходит "
                "на маркетплейс как есть.",
                elem_classes="fitter-hint",
            )

            batch_state = gr.State()
            edit_state = gr.State()

            with gr.Group(visible=False) as edit_group:
                edit_label = gr.Markdown()
                gr.Markdown(
                    "**Зелёная кисть** — вернуть товару, **красная** — отправить в фон, "
                    "**ластик** — стереть свой мазок. Размер меняется в редакторе. "
                    "После «Применить» файл в папке результата и архив обновляются сами.",
                    elem_classes="fitter-hint",
                )
                with gr.Row():
                    batch_slider = gr.ImageSlider(label="До / после", height=420)
                    batch_editor = gr.ImageEditor(
                        label="Правка маски: зелёным — товар, красным — фон",
                        type="numpy",
                        brush=gr.Brush(
                            colors=["#16D95A", "#FF3B30"], color_mode="fixed", default_size=28
                        ),
                        eraser=gr.Eraser(default_size=28),
                        layers=False,
                        transforms=[],
                        height=420,
                    )
                with gr.Row():
                    batch_apply = gr.Button("Применить правку", variant="primary")
                    batch_reset = gr.Button("Сбросить правку")
                batch_md = gr.Markdown()

            run_btn.click(
                run_batch_ui,
                [files, folder, *controls],
                [summary, table, gallery, zip_btn, report_btn, batch_state],
            )
            gallery.select(
                pick_from_batch,
                [batch_state],
                [edit_group, edit_label, batch_slider, batch_editor, batch_md, edit_state],
            )
            batch_apply.click(
                apply_batch_edit,
                [batch_editor, edit_state],
                [batch_slider, batch_editor, batch_md, zip_btn, edit_state],
            )
            batch_reset.click(
                reset_batch_edit,
                [edit_state],
                [batch_slider, batch_editor, batch_md, zip_btn, edit_state],
            )

        with gr.Tab("Один кадр и правка маски"):
            gr.Markdown(
                "Обработайте кадр, а затем поправьте маску руками, если программа "
                "где-то ошиблась. **Зелёная кисть** — вернуть товару, **красная** — "
                "отправить в фон. Размер кисти и ластика меняется в самом редакторе."
            )
            state = gr.State()
            with gr.Row():
                with gr.Column(scale=1):
                    single = gr.Image(label="Кадр", type="numpy", height=320)
                    prev_btn = gr.Button("Показать результат", variant="primary")
                    metrics_md = gr.Markdown()
                with gr.Column(scale=2):
                    slider = gr.ImageSlider(label="До / после", height=440)
                    editor = gr.ImageEditor(
                        label="Правка маски: зелёным — товар, красным — фон",
                        type="numpy",
                        brush=gr.Brush(
                            colors=["#16D95A", "#FF3B30"],
                            color_mode="fixed",
                            default_size=28,
                        ),
                        eraser=gr.Eraser(default_size=28),
                        layers=False,
                        transforms=[],
                        height=440,
                    )
                    with gr.Row():
                        apply_btn = gr.Button("Применить правку", variant="primary")
                        reset_btn = gr.Button("Сбросить правку")
                    frame_btn = gr.DownloadButton("Скачать этот кадр", interactive=False)

            with gr.Row():
                preset_name = gr.Textbox(label="Имя нового пресета", placeholder="мой_вариант")
                save_btn = gr.Button("Сохранить пресет")
            save_msg = gr.Markdown()

            prev_btn.click(
                preview_one, [single, *controls], [slider, editor, metrics_md, frame_btn, state]
            )
            apply_btn.click(
                apply_mask_edit, [editor, state], [slider, editor, metrics_md, frame_btn, state]
            )
            reset_btn.click(
                reset_mask_edit, [state], [slider, editor, metrics_md, frame_btn, state]
            )
            save_btn.click(save_preset_ui, [preset_name, *controls], [save_msg])

    return demo


DEFAULT_PORT = 7860


def _port_is_free(host: str, port: int) -> bool:
    """Проверяет, свободен ли порт, реальной попыткой занять его.

    Намеренно без SO_REUSEADDR: на Windows этот флаг разрешает биндиться к уже
    занятому порту, и проверка стала бы врать.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _pick_port(host: str, preferred: int | None, span: int = 60) -> tuple[int | None, bool]:
    """Выбирает порт. Возвращает (порт или None, был ли занят желаемый).

    Порт подбирается здесь, а не отдаётся на откуп Gradio, по двум причинам.
    Во-первых, тогда мы знаем номер заранее и можем честно сказать человеку
    «7860 занят, поднимаю на 7861» вместо молчаливого открытия второго окна.
    Во-вторых, явно заданный `--port` должен оставаться обещанием: если занят
    именно он, это ошибка, а не повод тихо уехать на соседний.
    """
    first = preferred or DEFAULT_PORT
    if _port_is_free(host, first):
        return first, False
    if preferred is not None:
        return None, True
    for candidate in range(first + 1, first + span):
        if _port_is_free(host, candidate):
            return candidate, True
    return None, True


def _lan_ip() -> str | None:
    """Локальный IP машины в сети — чтобы подсказать адрес для коллег.

    UDP-сокет с connect() наружу не отправляет ни одного пакета: вызов лишь
    заставляет систему выбрать маршрут и, вместе с ним, исходящий адрес.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def _announce(host: str, port: int, was_busy: bool) -> None:
    """Печатает адрес до старта: после blocking-вызова launch() будет поздно."""
    if was_busy:
        print(
            f"\n  Порт {DEFAULT_PORT} занят — похоже, программа уже открыта "
            f"в другом окне.\n  Запускаю на порту {port}."
        )
    if host in ("0.0.0.0", "::"):
        ip = _lan_ip()
        where = f"http://{ip}:{port}" if ip else f"http://ВАШ-IP-АДРЕС:{port}"
        print(f"\n  Адрес для коллег: {where}\n")
    else:
        print(f"\n  Адрес: http://{host}:{port}\n")


def launch(host: str = "127.0.0.1", port: int | None = None, share: bool = False, **extra) -> None:
    """Поднимает интерфейс на локальной машине.

    Набор аргументов launch() у Gradio меняется от версии к версии (в 6.0 уехали
    и theme, и show_api), а на машине пользователя встанет то, что встанет.
    Поэтому неподдерживаемые аргументы отбрасываются по сигнатуре, а не подбираются
    по номеру версии: интерфейс поднимется на любой разумной версии.
    """
    chosen, was_busy = _pick_port(host, port)
    if chosen is None:
        _report_no_port(host, port)
        raise SystemExit(1)

    demo = build()
    candidate = {
        "server_name": host,
        "server_port": chosen,
        "share": share,
        "inbrowser": host == "127.0.0.1",
        "show_api": False,
        "theme": gr.themes.Soft() if _GRADIO_MAJOR >= 6 else None,
        **extra,
    }
    accepted = set(inspect.signature(demo.launch).parameters)
    kwargs = {k: v for k, v in candidate.items() if k in accepted and v is not None}

    _announce(host, chosen, was_busy)
    try:
        demo.launch(**kwargs)
    except OSError:
        # Между проверкой порта и стартом сервера его мог занять кто-то ещё.
        # Человеку, который не программист, стек-трейс здесь бесполезен.
        _report_no_port(host, chosen)
        raise SystemExit(1) from None


def _report_no_port(host: str, port: int | None) -> None:
    print(
        f"\n  Не удалось занять порт {port if port else DEFAULT_PORT}.\n"
        f"\n  Скорее всего программа уже запущена в другом окне — закройте его "
        f"и попробуйте снова.\n"
        f"  Либо укажите другой порт вручную:  fitter ui --port 7870\n"
    )
