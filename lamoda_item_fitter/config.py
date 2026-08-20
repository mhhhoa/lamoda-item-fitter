"""Пресет с правилами маркетплейса.

Значения по умолчанию выверены по 19 фото, прошедшим модерацию Ламоды
(см. reference/ и `analyze`). Менять правила следует в presets/lamoda.json
или в файле lamoda.json рядом с exe — код трогать не нужно.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

PRESET_FILENAME = "lamoda.json"


def resource_dir() -> Path:
    """Каталог с ресурсами: временная папка PyInstaller или корень репозитория."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """Каталог, откуда запущена программа (рядом с exe при сборке)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


@dataclass(frozen=True)
class Canvas:
    width: int = 1524
    height: int = 2200


@dataclass(frozen=True)
class Margins:
    top: int = 200
    bottom: int = 360
    left: int = 200
    right: int = 200


@dataclass(frozen=True)
class BackgroundCfg:
    #: фон светлее этого уровня считается допустимым
    min_level: int = 220
    #: доля стороны кадра, по рамке которой оценивается цвет фона
    border_fraction: float = 0.02
    #: пиксели ближе этого расстояния к фону приводятся ровно к цвету фона
    flatten_threshold: int = 8
    #: на сколько расширяется маска товара, защищаемая от выравнивания
    protect_dilate_px: int = 4
    #: ширина растушёвки края вставки, страховка для градиентного фона
    feather: int = 32


@dataclass(frozen=True)
class MaskCfg:
    #: коридор для порога, вычисленного от шума фона
    solid_threshold_min: int = 6
    solid_threshold_max: int = 30
    #: порог мягкой маски — ловит тень и полупрозрачные детали
    soft_threshold: int = 3
    #: порог заведомо контрастной части товара — опора для распознавания тени
    core_threshold: int = 25
    #: тенью может считаться только материал слабее этого порога
    shadow_max_contrast: int = 25
    #: о тени сообщаем, только если она заметна — иначе это мягкий край подошвы
    shadow_notice_ratio: float = 0.05
    close_px: int = 5
    #: компоненты мельче этой доли крупнейшего отбрасываются (пыль, подписи)
    min_component_fraction: float = 0.02
    #: касание края в пределах стольких пикселей считается обрезкой
    edge_touch_px: int = 2
    #: расхождение габарита между масками, после которого предупреждаем
    uncertainty_warn: float = 0.04


@dataclass(frozen=True)
class OutputCfg:
    format: str = "jpeg"
    jpeg_quality: int = 100
    jpeg_subsampling: int = 0
    max_bytes: int = 5 * 1024 * 1024
    quality_ladder: tuple[int, ...] = (100, 97, 95, 92, 90, 88, 85)
    png_optimize: bool = True
    suffix: str = "_lamodafit"
    suffix_on_folder: bool = False


@dataclass(frozen=True)
class Preset:
    name: str = "Ламода — обувь"
    canvas: Canvas = field(default_factory=Canvas)
    margins: Margins = field(default_factory=Margins)
    #: доля рабочей зоны, которую занимает товар (эталоны дали ровно 1.0)
    fill: float = 1.0
    #: exclude — тень не входит в габарит; include — входит; remove — стирается
    shadow_mode: str = "exclude"
    #: passthrough — макро переносится без подгонки; skip — пропускается;
    #: fit — вписывается по видимой части
    cropped_policy: str = "passthrough"
    #: длинная сторона рабочей копии, на которой идёт анализ
    analysis_max_side: int = 1500
    #: во сколько раз максимум допустимо увеличивать товар
    max_upscale: float = 8.0
    #: товар мельче этой доли площади кадра — это не товар, а мусор или
    #: случайный снимок: подгонять такое нельзя ни при каком масштабе
    min_item_fraction: float = 0.002
    #: потолок промежуточного изображения, мегапикселей
    max_working_megapixels: float = 80.0
    background: BackgroundCfg = field(default_factory=BackgroundCfg)
    mask: MaskCfg = field(default_factory=MaskCfg)
    output: OutputCfg = field(default_factory=OutputCfg)

    # --- производная геометрия -------------------------------------------------

    @property
    def zone_width(self) -> int:
        """Ширина рабочей зоны: 1524 − 200 − 200 = 1124."""
        return self.canvas.width - self.margins.left - self.margins.right

    @property
    def zone_height(self) -> int:
        """Высота рабочей зоны: 2200 − 200 − 360 = 1640."""
        return self.canvas.height - self.margins.top - self.margins.bottom

    @property
    def baseline_y(self) -> int:
        """Линия, которой обязан касаться низ товара: 2200 − 360 = 1840."""
        return self.canvas.height - self.margins.bottom

    @property
    def center_x(self) -> float:
        return self.canvas.width / 2.0

    # --- сериализация ----------------------------------------------------------

    def replace(self, **changes: Any) -> "Preset":
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        def unpack(obj: Any) -> Any:
            if hasattr(obj, "__dataclass_fields__"):
                return {k: unpack(getattr(obj, k)) for k in obj.__dataclass_fields__}
            if isinstance(obj, tuple):
                return list(obj)
            return obj

        return unpack(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Preset":
        def build(klass: type, raw: Any) -> Any:
            if not isinstance(raw, dict):
                return raw
            fields = klass.__dataclass_fields__
            kwargs = {k: v for k, v in raw.items() if k in fields}
            if klass is OutputCfg and "quality_ladder" in kwargs:
                kwargs["quality_ladder"] = tuple(kwargs["quality_ladder"])
            return klass(**kwargs)

        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        for key, klass in (
            ("canvas", Canvas), ("margins", Margins), ("background", BackgroundCfg),
            ("mask", MaskCfg), ("output", OutputCfg),
        ):
            if key in known:
                known[key] = build(klass, known[key])
        return cls(**known)

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Preset":
        """Пресет из файла; без аргумента — рядом с exe, иначе встроенный."""
        if path is not None:
            return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        for candidate in (app_dir() / PRESET_FILENAME, resource_dir() / "presets" / PRESET_FILENAME):
            if candidate.is_file():
                try:
                    return cls.from_dict(json.loads(candidate.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
        return cls()

    def save(self, path: Path | str) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
