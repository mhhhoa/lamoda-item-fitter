"""Настройки сжатия и их сохранение между запусками."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

MB = 1024 * 1024

#: Лимит веса файла на Ламоде.
LAMODA_MAX_BYTES = 5 * MB

#: Форматы, которые умеем читать (Pillow + pillow-heif).
INPUT_EXTENSIONS = {
    ".jpg", ".jpeg", ".jpe", ".jfif",
    ".png", ".webp", ".avif",
    ".heic", ".heif", ".hif",
    ".tif", ".tiff", ".bmp", ".gif", ".ppm", ".tga", ".ico",
}

#: Форматы, в которые умеем писать. Ключ — то, что хранится в настройках.
OUTPUT_FORMATS = {
    "auto": ("Как в оригинале", None),
    "jpeg": ("JPEG", ".jpg"),
    "png": ("PNG", ".png"),
    "webp": ("WebP", ".webp"),
    "avif": ("AVIF", ".avif"),
}

#: Форматы с потерями — для них имеет смысл ползунок качества.
LOSSY_FORMATS = {"jpeg", "webp", "avif"}

MODE_LOSSLESS = "lossless"
MODE_SMART = "smart"
MODE_MANUAL = "manual"

MODES = {
    MODE_LOSSLESS: "Без потерь",
    MODE_SMART: "Умный",
    MODE_MANUAL: "Ручной",
}

CONFLICT_SUFFIX = "suffix"
CONFLICT_OVERWRITE = "overwrite"
CONFLICT_SKIP = "skip"


@dataclass
class Settings:
    """Полный набор параметров обработки.

    Поля разбиты на три группы: что делать с картинкой, куда её класть
    и как вести себя при конфликтах имён.
    """

    # --- Целевой вес -----------------------------------------------------
    limit_enabled: bool = True
    target_mb: float = 5.0
    #: Реальный лимит берём чуть ниже заявленного: маркетплейсы считают
    #: мегабайт по-разному, а 2% запаса стоят копеек по качеству.
    safety_margin: float = 0.02

    # --- Режим и качество ------------------------------------------------
    mode: str = MODE_SMART
    quality: int = 92
    min_quality: int = 70

    # --- Разрешение ------------------------------------------------------
    max_side_enabled: bool = True
    max_side: int = 2400
    min_side_enabled: bool = True
    min_side: int = 1200
    allow_downscale: bool = True

    # --- Формат и метаданные --------------------------------------------
    output_format: str = "auto"
    keep_metadata: bool = False
    convert_to_srgb: bool = True
    progressive: bool = True
    subsampling: str = "auto"  # auto | 444 | 422 | 420

    # --- Выгрузка --------------------------------------------------------
    output_dir: str = ""
    keep_structure: bool = True
    copy_when_already_small: bool = True
    on_conflict: str = CONFLICT_SUFFIX
    name_suffix: str = ""

    # --- Прочее ----------------------------------------------------------
    threads: int = 0  # 0 = определить по числу ядер
    recent_output_dirs: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------------
    @property
    def target_bytes(self) -> int | None:
        """Лимит в байтах с учётом запаса, либо None если лимит выключен."""
        if not self.limit_enabled:
            return None
        return int(self.target_mb * MB * (1.0 - self.safety_margin))

    @property
    def effective_threads(self) -> int:
        if self.threads > 0:
            return self.threads
        import os

        return max(1, min(8, (os.cpu_count() or 4)))

    def normalized(self) -> "Settings":
        """Приводит взаимозависимые поля в согласованное состояние."""
        copy = Settings(**asdict(self))
        copy.quality = max(1, min(100, copy.quality))
        copy.min_quality = max(1, min(copy.quality, copy.min_quality))
        copy.max_side = max(64, copy.max_side)
        copy.min_side = max(16, min(copy.min_side, copy.max_side))
        copy.target_mb = max(0.05, copy.target_mb)
        if copy.mode == MODE_LOSSLESS:
            # В режиме без потерь пережимать и уменьшать нечего.
            copy.allow_downscale = False
        return copy

    # --- Сериализация ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    @staticmethod
    def config_path() -> Path:
        import os

        base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
        return Path(base) / "LamodaItemFitter" / "settings.json"

    def save(self) -> None:
        path = self.config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            # Настройки — приятный бонус, а не повод падать.
            pass

    @classmethod
    def load(cls) -> "Settings":
        path = cls.config_path()
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return cls()
