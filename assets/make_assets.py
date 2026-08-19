"""Генерация иконки и заставки. Запускать при изменении оформления:
    python assets/make_assets.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
INK = (17, 17, 20)
PAPER = (246, 246, 247)
LINE = (30, 170, 110)
MUTED = (120, 120, 130)


def icon(size: int = 512) -> Image.Image:
    """Знак повторяет суть программы: товар, стоящий на нижней линии отступа."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = int(size * 0.22)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=INK)

    unit = size / 100.0
    left, right = 22 * unit, 78 * unit
    top, baseline = 18 * unit, 74 * unit
    draw.rounded_rectangle([left, top, right, baseline], int(2 * unit),
                           outline=MUTED, width=max(2, int(1.6 * unit)))
    # силуэт: подошва во всю ширину зоны и задник повыше — «вид сбоку»
    sole_top = baseline - 11 * unit
    draw.rounded_rectangle([left, sole_top, right, baseline], int(3 * unit), fill=PAPER)
    draw.rounded_rectangle([right - 22 * unit, baseline - 26 * unit, right, baseline],
                           int(4 * unit), fill=PAPER)
    draw.line([10 * unit, baseline, 90 * unit, baseline], fill=LINE, width=max(3, int(2.6 * unit)))
    return image


def splash(width: int = 460, height: int = 200) -> Image.Image:
    image = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, width - 1, height - 1], 16, fill=PAPER, outline=(226, 226, 230))
    mark = icon(88).convert("RGBA")
    image.paste(mark, (28, height // 2 - 44), mark)
    draw.text((136, height // 2 - 22), "Lamoda Item Fitter", fill=INK)
    draw.text((136, height // 2 + 2), "Запускается, подождите несколько секунд…", fill=MUTED)
    draw.line([136, height // 2 + 34, width - 40, height // 2 + 34], fill=(226, 226, 230), width=2)
    return image


if __name__ == "__main__":
    master = icon(512)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(HERE / "icon.ico", sizes=sizes)
    master.resize((256, 256), Image.LANCZOS).save(HERE / "icon.png")
    splash().save(HERE / "splash.png")
    print("готово:", HERE / "icon.ico", HERE / "icon.png", HERE / "splash.png")
