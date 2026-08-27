import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_photo(width: int, height: int, seed: int = 1) -> Image.Image:
    """Картинка с деталями — ровная заливка сжимается нереалистично хорошо."""
    import random

    random.seed(seed)
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for offset in range(0, height, 3):
        draw.rectangle(
            [0, offset, width, offset + 3],
            fill=(90 + offset % 120, 70 + (offset * 5) % 150, 130 + (offset * 3) % 100),
        )
    for _ in range(600):
        x, y = random.randint(0, width), random.randint(0, height)
        radius = random.randint(4, 60)
        draw.ellipse(
            [x - radius, y - radius, x + radius, y + radius],
            fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)),
        )
    pixels = image.load()
    for _ in range(width * height // 4):
        x, y = random.randint(0, width - 1), random.randint(0, height - 1)
        r, g, b = pixels[x, y]
        pixels[x, y] = (
            max(0, min(255, r + random.randint(-45, 45))),
            max(0, min(255, g + random.randint(-45, 45))),
            max(0, min(255, b + random.randint(-45, 45))),
        )
    return image


@pytest.fixture
def photo():
    return make_photo


@pytest.fixture
def tree(tmp_path, photo):
    """Небольшое дерево папок, похожее на реальную выгрузку со съёмки."""
    root = tmp_path / "shoot"
    (root / "dress_blue").mkdir(parents=True)
    (root / "dress_red").mkdir(parents=True)
    photo(1400, 1750, 1).save(root / "dress_blue" / "front.jpg", quality=97, subsampling=0)
    photo(900, 1100, 2).save(root / "dress_blue" / "back.jpg", quality=92)
    photo(1400, 1750, 3).save(root / "dress_red" / "front.jpg", quality=97, subsampling=0)
    photo(600, 600, 4).save(root / "cover.png")
    (root / "notes.txt").write_text("не картинка", encoding="utf-8")
    return root
