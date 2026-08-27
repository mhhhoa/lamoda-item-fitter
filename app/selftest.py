"""Самопроверка собранного приложения.

Запуск: LamodaItemFitter.exe --selftest отчёт.txt

Собранный exe нельзя потрогать руками в CI, а сломаться при упаковке может
многое: не доехали ресурсы, не подтянулись библиотеки HEIF или mozjpeg, не
поднялся Qt. Проверка гоняет всё это на готовом файле и пишет отчёт — окно
приложения без консоли ничего не выводит в стандартный поток.
"""

from __future__ import annotations

import io
import os
import sys
import traceback
from pathlib import Path

REQUIRED_ASSETS = [
    "icon.png", "icon.ico", "splash.png",
    "check.png", "check_disabled.png", "chevron_up.png", "chevron_down.png",
]


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.failed = 0

    def check(self, name: str, action) -> None:
        try:
            detail = action()
        except Exception as error:  # noqa: BLE001 - отчёт важнее стека
            self.failed += 1
            self.lines.append(f"[ПРОВАЛ] {name}: {error!r}")
            self.lines.append(traceback.format_exc().rstrip())
        else:
            self.lines.append(f"[ок]     {name}" + (f" — {detail}" if detail else ""))

    def text(self) -> str:
        verdict = "ВСЁ ХОРОШО" if not self.failed else f"ПРОВАЛОВ: {self.failed}"
        return "\n".join([*self.lines, "", verdict, ""])


def _sample(width: int = 900, height: int = 1200):
    """Картинка с деталями — ровная заливка сожмётся нереалистично хорошо."""
    import random

    from PIL import Image, ImageDraw

    random.seed(11)
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for offset in range(0, height, 3):
        draw.rectangle([0, offset, width, offset + 3],
                       fill=(80 + offset % 150, 60 + (offset * 7) % 170, 120 + (offset * 3) % 120))
    for _ in range(500):
        x, y = random.randint(0, width), random.randint(0, height)
        radius = random.randint(5, 70)
        draw.ellipse([x - radius, y - radius, x + radius, y + radius],
                     fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    pixels = image.load()
    for _ in range(width * height // 3):
        x, y = random.randint(0, width - 1), random.randint(0, height - 1)
        r, g, b = pixels[x, y]
        pixels[x, y] = (min(255, r + random.randint(0, 50)),
                        min(255, g + random.randint(0, 50)),
                        min(255, b + random.randint(0, 50)))
    return image


def run(report_path: Path | None = None) -> int:
    report = Report()
    report.lines.append(f"Python {sys.version.split()[0]}")
    report.lines.append(f"Запуск из {'сборки' if hasattr(sys, '_MEIPASS') else 'исходников'}")

    # --- Ресурсы ------------------------------------------------------
    def assets():
        from .ui.theme import assets_dir

        directory = Path(assets_dir())
        if not directory.is_dir():
            raise AssertionError("папка assets не найдена в сборке")
        missing = [name for name in REQUIRED_ASSETS if not (directory / name).is_file()]
        if missing:
            raise AssertionError(f"не хватает файлов: {', '.join(missing)}")
        return f"{len(REQUIRED_ASSETS)} файлов на месте"

    report.check("Ресурсы интерфейса", assets)

    # --- Библиотеки изображений ---------------------------------------
    def formats():
        from PIL import features

        available = [name for name in ("jpg", "webp", "avif") if features.check(name)]
        if "jpg" not in available:
            raise AssertionError("нет поддержки JPEG")
        return ", ".join(available)

    report.check("Форматы Pillow", formats)

    def heif():
        from .core.compressor import HEIF_AVAILABLE, HEIF_ERROR

        if not HEIF_AVAILABLE:
            raise AssertionError(
                f"pillow-heif не подтянулся ({HEIF_ERROR or 'причина неизвестна'}) — "
                "HEIC с айфона читаться не будет"
            )
        import pillow_heif

        buffer = io.BytesIO()
        pillow_heif.from_pillow(_sample(200, 200)).save(buffer, format="HEIF", quality=80)
        from PIL import Image

        with Image.open(io.BytesIO(buffer.getvalue())) as opened:
            opened.load()
            return f"HEIC читается, {opened.size[0]}×{opened.size[1]}"

    report.check("HEIC/HEIF", heif)

    def mozjpeg():
        from .core.compressor import MOZJPEG_AVAILABLE, MOZJPEG_ERROR

        if not MOZJPEG_AVAILABLE:
            raise AssertionError(
                f"mozjpeg не подтянулся ({MOZJPEG_ERROR or 'причина неизвестна'}) — "
                "режим «без потерь» работать не будет"
            )
        return "доступен"

    report.check("Оптимизация без потерь", mozjpeg)

    # --- Сжатие -------------------------------------------------------
    def compression():
        from .core.compressor import Status, compress_bytes
        from .core.settings import Settings

        buffer = io.BytesIO()
        _sample().save(buffer, format="JPEG", quality=98, subsampling=0)
        raw = buffer.getvalue()

        settings = Settings(target_mb=0.25, max_side_enabled=True, max_side=800)
        result = compress_bytes(raw, settings)

        if result.status is Status.ERROR:
            raise AssertionError("сжатие вернуло ошибку")
        if len(result.data) > settings.target_bytes:
            raise AssertionError(
                f"не уложились в лимит: {len(result.data)} > {settings.target_bytes}"
            )
        if max(result.width, result.height) > 800:
            raise AssertionError(
                f"не сработало ограничение размера: {result.width}×{result.height}"
            )
        return (f"{len(raw) // 1024} КБ → {len(result.data) // 1024} КБ, "
                f"{result.width}×{result.height}, качество {result.quality}")

    report.check("Подгонка под лимит", compression)

    def lossless():
        from .core.compressor import Status, compress_bytes
        from .core.settings import Settings


        buffer = io.BytesIO()
        _sample(500, 500).save(buffer, format="JPEG", quality=90)
        raw = buffer.getvalue()
        result = compress_bytes(raw, Settings(target_mb=5.0, max_side_enabled=False))
        if result.status is not Status.LOSSLESS:
            raise AssertionError(
                f"ожидали режим без потерь, получили {result.status.value}"
                + (f" ({result.note})" if result.note else "")
            )
        data = result.data
        from PIL import Image

        with Image.open(io.BytesIO(data)) as after, Image.open(io.BytesIO(raw)) as before:
            if after.tobytes() != before.tobytes():
                raise AssertionError("пиксели изменились там, где обещали их не трогать")
        return f"{len(raw) // 1024} КБ → {len(data) // 1024} КБ, пиксели совпадают"

    report.check("Режим без потерь", lossless)

    def broken_file(tmp=Path(os.environ.get("TEMP", ".")) / "lif_broken.jpg"):
        """Битый файл обязан стать понятной ошибкой, а не уехать в выгрузку."""
        from .core.compressor import compress_file
        from .core.settings import Settings
        from .pipeline import _readable

        tmp.write_bytes(b"\xff\xd8\xff\xe0" + "это не картинка".encode("utf-8"))
        destination = tmp.with_name("lif_broken_out.jpg")
        try:
            try:
                result = compress_file(tmp, lambda extension: destination, Settings())
            except Exception as error:
                message = _readable(error)
                if message == repr(error) or not message:
                    raise AssertionError(f"нечитаемое сообщение об ошибке: {error!r}")
                if destination.exists():
                    raise AssertionError("битый файл всё-таки попал в выгрузку")
                return f"стал ошибкой: {message}"
            raise AssertionError(
                f"битый файл прошёл как {result.status.value} — он бы уехал на площадку"
            )
        finally:
            tmp.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)

    report.check("Битый файл", broken_file)

    # --- Интерфейс ----------------------------------------------------
    def interface():
        from PySide6.QtWidgets import QApplication

        from .core.settings import Settings
        from .ui.main_window import MainWindow
        from .ui.theme import stylesheet

        css = stylesheet()
        if "check.png" not in css:
            raise AssertionError("в стилях не проставились пути к ресурсам")

        application = QApplication.instance() or QApplication([])
        application.setStyle("Fusion")
        application.setStyleSheet(css)
        window = MainWindow(Settings())
        window.show()
        application.processEvents()
        size = window.size()
        window.close()
        return f"окно поднялось, {size.width()}×{size.height()}"

    report.check("Интерфейс Qt", interface)

    text = report.text()
    if report_path is not None:
        report_path.write_text(text, encoding="utf-8")
    try:
        print(text)
    except Exception:
        pass  # у сборки без консоли потока вывода нет
    return 1 if report.failed else 0
