"""Настройки обработки. Все числа спецификации живут здесь и в YAML-пресетах,
чтобы правились без единой строчки кода.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path

import yaml

__all__ = ["Settings", "load_preset", "list_presets", "PRESET_DIR"]

PRESET_DIR = Path(__file__).resolve().parents[2] / "presets"


@dataclass
class Settings:
    """Параметры обработки одного кадра и экспорта."""

    # --- матирование ---
    matting: str = "rembg"
    refine_alpha: bool = True

    repair_mask: bool = True
    """Чинить ли ошибки маски, дающие светлые пятна на товаре.

    Выключать стоит только при разборе полётов: без починки островок, ошибочно
    помеченный фоном внутри товара, осветляется вместе с фоном."""

    matting_post_process: bool = False
    """Сглаживание маски средствами rembg.

    По умолчанию выключено: оно уплотняет маску и съедает полупрозрачную кромку,
    а именно она нужна нашему уточнению кромки по модели фона. Чистку маски мы
    делаем сами и делаем осмысленнее — с оглядкой на то, как выглядит фон."""

    # --- модель фона ---
    poly_degree: int = 2
    """Степень полинома фона. 2 — почти всегда; 3 — сложный градиент или виньетка."""

    # --- художественные параметры ---
    wb_strength: float = 0.25
    """Насколько снимать цветной рефлекс фона с товара и модели (0..1).

    По смыслу это доля света, пришедшего на товар отражением от цветной циклорамы.
    В студийной схеме она обычно 10-25%, поэтому дефолт консервативный: снять
    оттенка больше, чем его было, — значит перекрасить товар. Точное значение
    подбирает `fitter calibrate` по эталонным парам."""

    reflection_strength: float = 1.0
    """1.0 — отражение как в оригинале, 0.0 — убрать совсем."""

    knee_low: float = 0.955
    knee_high: float = 0.992
    """Диапазон плавной дотяжки почти-белого до честного 255."""

    # --- вывод ---
    target_bg: str = "#FFFFFF"
    jpeg_quality: int = 95
    max_bytes: int = 10_485_760
    geometry_mode: str = "keep"  # keep | fit | cover
    out_width: int = 1500
    out_height: int = 2000

    # --- пороги QA ---
    min_white: int = 235
    """Ниже этого значения в углах кадр помечается замечанием (не ошибкой).

    Порог намеренно нестрогий: разница между 250 и 255 в углу на глаз не видна
    и на приёмку не влияет. Смысл проверки — поймать случай, когда фон реально
    остался серым, а не придираться к единицам."""
    max_product_delta_e: float = 3.0
    max_bg_residual: float = 0.030
    max_blown_ratio: float = 0.020

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(
                f"Неизвестные параметры в пресете: {', '.join(sorted(unknown))}.\n"
                f"Допустимые: {', '.join(sorted(known))}"
            )
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)

    def replace(self, **kwargs) -> "Settings":
        data = self.to_dict()
        data.update({k: v for k, v in kwargs.items() if v is not None})
        return Settings.from_dict(data)


def _flatten(data: dict) -> dict:
    """Разворачивает вложенный YAML в плоские поля Settings.

    В пресете удобнее писать сгруппированно (background/output/qa), а в коде
    удобнее плоская структура.
    """
    out: dict = {}
    for key, value in (data or {}).items():
        if isinstance(value, dict):
            out.update(value)
        else:
            out[key] = value
    return out


def load_preset(name_or_path: str | Path) -> Settings:
    """Загружает пресет по имени (из presets/) или по пути к YAML-файлу."""
    path = Path(name_or_path)
    if not path.exists():
        path = PRESET_DIR / f"{name_or_path}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Пресет {name_or_path!r} не найден. Доступны: {', '.join(list_presets())}"
        )
    with open(path, "r", encoding="utf-8") as fh:
        return Settings.from_dict(_flatten(yaml.safe_load(fh)))


def list_presets() -> list[str]:
    if not PRESET_DIR.exists():
        return []
    return sorted(p.stem for p in PRESET_DIR.glob("*.yaml"))
