import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lamoda_item_fitter.config import Preset  # noqa: E402


@pytest.fixture
def preset() -> Preset:
    return Preset.load(Path(__file__).resolve().parent.parent / "presets" / "lamoda.json")


def canvas(height: int, width: int, level: int = 246, noise: int = 0, seed: int = 0):
    """Пустой светлый фон, при необходимости с шумом матрицы."""
    array = np.full((height, width, 3), level, np.int16)
    if noise:
        rng = np.random.default_rng(seed)
        array += rng.integers(-noise, noise + 1, array.shape)
    return np.clip(array, 0, 255).astype(np.uint8)


def as_image(array: np.ndarray) -> Image.Image:
    return Image.fromarray(array)


@pytest.fixture
def make_canvas():
    return canvas


@pytest.fixture
def to_image():
    return as_image
