"""Визуальный интерфейс: локальная страница в браузере.

Рассчитан на работу без командной строки — открыть, перетащить кадры, забрать
результат. Тот же самый интерфейс поднимается для коллег по локальной сети:
достаточно запустить с --host 0.0.0.0.
"""

from __future__ import annotations

import inspect
import tempfile
import zipfile
from pathlib import Path

import gradio as gr
import numpy as np
import yaml

from . import report as repmod
from .batch import SUPPORTED_SUFFIXES, find_images
from .config import PRESET_DIR, Settings, list_presets, load_preset
from .matting import available_backends, get_backend
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

    matte_fn = get_backend(settings.matting)
    results, failures, rows, gallery = [], [], [], []

    for i, src in enumerate(progress.tqdm(paths, desc="Обработка")):
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
        except Exception as exc:  # noqa: BLE001
            failures.append((src, exc))
            rows.append([src.name, "ошибка", None, None, None, str(exc)[:200]])

    report_path = out_dir / "_отчёт.html"
    repmod.write_report(report_path, results, failures, preset_name=preset)

    archive = work / "результат.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(out_dir))

    tally = {v: sum(1 for r in results if r.verdict == v) for v in (OK, CHECK, FAIL)}
    summary = (
        f"### Обработано: {len(results)} из {len(paths)}\n\n"
        f"- готово без замечаний: **{tally[OK]}**\n"
        f"- проверить глазами: **{tally[CHECK]}**\n"
        f"- ошибки: **{tally[FAIL] + len(failures)}**\n\n"
        f"Смотреть глазами нужно только помеченные строки. "
        f"Подробности — в файле `_отчёт.html` внутри архива."
    )
    return summary, rows, gallery, str(archive), str(report_path)


# --- вкладка 2: настройка ---------------------------------------------------


def preview_one(image, preset, matting, wb, reflection, knee_low, degree, target_bg):
    if image is None:
        raise gr.Error("Загрузите один кадр для подбора настроек.")

    srgb = np.asarray(image, dtype=np.float32) / 255.0
    settings = _settings_from_ui(preset, matting, wb, reflection, knee_low, degree, target_bg)
    res = process_array(srgb, settings)
    m = res.report.metrics

    lines = [
        f"**Вердикт: {_BADGE[res.verdict]}**",
        "",
        f"- фон в углах: `{m.get('bg_corner_min')}` из 255",
        f"- сдвиг цвета товара: `ΔE2000 {m.get('product_delta_e')}` "
        f"(меньше 1 — глазом не видно)",
        f"- площадь отражения: `{m.get('reflection_before')}` → `{m.get('reflection_after')}`",
        f"- выбелено товара: `{m.get('blown_ratio')}`",
        f"- гладкость фона: `{m.get('bg_residual')}`",
        f"- время: `{res.timing['total']:.1f} с`",
    ]
    if res.report.notes:
        lines += ["", "**На что обратить внимание:**"] + [f"- {n}" for n in res.report.notes]

    before8 = np.round(np.clip(srgb, 0, 1) * 255).astype(np.uint8)
    after8 = np.round(np.clip(res.image, 0, 1) * 255).astype(np.uint8)
    mask8 = np.round(np.clip(res.alpha, 0, 1) * 255).astype(np.uint8)
    return (before8, after8), mask8, "\n".join(lines)


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


# --- вкладка 3: сверка с подрядчиком ----------------------------------------


def compare_ui(folder, preset, progress=gr.Progress()):
    from .compare import compare_folder

    if not folder or not folder.strip():
        raise gr.Error("Укажите путь к папке с парами «артикул_before» / «артикул_after».")

    scores = compare_folder(Path(folder.strip()), load_preset(preset))
    rows = [
        [s.name, s.delta_e_mean, s.delta_e_product, s.delta_e_background, s.ssim, s.verdict]
        for s in sorted(scores, key=lambda x: -x.delta_e_mean)
    ]
    mean = float(np.mean([s.delta_e_mean for s in scores]))

    work = _workdir()
    report_path = work / "сверка.html"
    repmod.write_compare_report(report_path, scores, preset_name=preset)

    summary = (
        f"### Среднее расхождение с эталонами: ΔE2000 = {mean:.2f}\n\n"
        "Меньше 1 — отличие неразличимо глазом. 1–2 — заметно только встык. "
        "2–3,5 — практически неразличимо в карточке. Больше 5 — видно сразу."
    )
    gallery = [
        (s.ours, f"{s.name} · наш") for s in scores
    ] + [(s.reference, f"{s.name} · подрядчик") for s in scores]
    return summary, rows, gallery, str(report_path)


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
                    0.90, 0.99, base.knee_low, step=0.005,
                    label="Порог дотяжки белого",
                    info="Ниже — фон белее, но светлый товар рискует слиться.",
                )
                degree = gr.Slider(
                    1, 3, base.poly_degree, step=1,
                    label="Степень модели фона",
                    info="2 — обычная циклорама. 3 — сложный градиент или виньетка.",
                )

        with gr.Tab("Пакет"):
            gr.Markdown(
                "Перетащите кадры **или** впишите путь к папке на этом компьютере."
            )
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
            gallery = gr.Gallery(label="Результат", columns=4, height=340)
            with gr.Row():
                zip_out = gr.File(label="Архив с готовыми кадрами")
                report_out = gr.File(label="HTML-отчёт")

            run_btn.click(
                run_batch_ui,
                [files, folder, preset, matting, wb, reflection, knee_low, degree, target_bg],
                [summary, table, gallery, zip_out, report_out],
            )

        with gr.Tab("Настройка на одном кадре"):
            gr.Markdown(
                "Подберите вид на одном кадре, затем сохраните как пресет "
                "и используйте его на вкладке «Пакет»."
            )
            with gr.Row():
                with gr.Column(scale=1):
                    single = gr.Image(label="Кадр", type="numpy", height=340)
                    prev_btn = gr.Button("Показать результат", variant="primary")
                    metrics_md = gr.Markdown()
                with gr.Column(scale=2):
                    slider = gr.ImageSlider(label="До / после", height=460)
                    mask_view = gr.Image(label="Маска товара", height=200)
            with gr.Row():
                preset_name = gr.Textbox(label="Имя нового пресета", placeholder="мой_вариант")
                save_btn = gr.Button("Сохранить пресет")
            save_msg = gr.Markdown()

            prev_btn.click(
                preview_one,
                [single, preset, matting, wb, reflection, knee_low, degree, target_bg],
                [slider, mask_view, metrics_md],
            )
            save_btn.click(
                save_preset_ui,
                [preset_name, preset, matting, wb, reflection, knee_low, degree, target_bg],
                [save_msg],
            )

        with gr.Tab("Сверка с подрядчиком"):
            gr.Markdown(
                "Сравнение нашей обработки с эталонами. В папке должны лежать пары "
                "файлов: `артикул_before.jpg` и `артикул_after.jpg`."
            )
            cmp_folder = gr.Textbox(label="Папка с парами", placeholder="./samples")
            cmp_btn = gr.Button("Сверить", variant="primary")
            cmp_summary = gr.Markdown()
            cmp_table = gr.Dataframe(
                headers=["артикул", "ΔE общий", "ΔE товара", "ΔE фона", "SSIM", "вывод"],
                label="Расхождение с эталоном",
                wrap=True,
            )
            cmp_gallery = gr.Gallery(label="Наш результат и эталон", columns=4, height=340)
            cmp_report = gr.File(label="HTML-отчёт по сверке")
            cmp_btn.click(
                compare_ui,
                [cmp_folder, preset],
                [cmp_summary, cmp_table, cmp_gallery, cmp_report],
            )

    return demo


def launch(host: str = "127.0.0.1", port: int = 7860, share: bool = False, **extra) -> None:
    """Поднимает интерфейс на локальной машине.

    Набор аргументов launch() у Gradio меняется от версии к версии (в 6.0 уехали
    и theme, и show_api), а на машине пользователя встанет то, что встанет.
    Поэтому неподдерживаемые аргументы отбрасываются по сигнатуре, а не подбираются
    по номеру версии: интерфейс поднимется на любой разумной версии.
    """
    demo = build()
    candidate = {
        "server_name": host,
        "server_port": port,
        "share": share,
        "inbrowser": host == "127.0.0.1",
        "show_api": False,
        "theme": gr.themes.Soft() if _GRADIO_MAJOR >= 6 else None,
        **extra,
    }
    accepted = set(inspect.signature(demo.launch).parameters)
    demo.launch(**{k: v for k, v in candidate.items() if k in accepted and v is not None})
