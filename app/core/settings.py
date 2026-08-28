"""Настройки обработки, пропорции кадра и профили."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

MB = 1024 * 1024

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

# --- Кадрирование под точный размер ---------------------------------------
FIT_COVER = "cover"
FIT_CONTAIN = "contain"
FIT_STRETCH = "stretch"

FIT_MODES = {
    FIT_COVER: "Заполнить с обрезкой",
    FIT_CONTAIN: "Вписать целиком",
    FIT_STRETCH: "Растянуть",
}

#: Куда прижимать кадр: при обрезке — что оставить, при вписывании — где
#: разместить фотографию среди полей.
ANCHORS = {
    "top_left": "Слева сверху",
    "top": "Сверху",
    "top_right": "Справа сверху",
    "left": "Слева",
    "center": "По центру",
    "right": "Справа",
    "bottom_left": "Слева снизу",
    "bottom": "Снизу",
    "bottom_right": "Справа снизу",
}

PAD_WHITE = "white"
PAD_BLACK = "black"
PAD_TRANSPARENT = "transparent"
PAD_EDGE = "edge"
PAD_CUSTOM = "custom"

PAD_MODES = {
    PAD_WHITE: "Белый",
    PAD_BLACK: "Чёрный",
    PAD_TRANSPARENT: "Прозрачный",
    PAD_EDGE: "Цвет из угла кадра",
    PAD_CUSTOM: "Свой цвет",
}

SHARPEN_OFF = "off"
SHARPEN_LIGHT = "light"
SHARPEN_STRONG = "strong"

SHARPEN_LEVELS = {
    SHARPEN_OFF: "Выключена",
    SHARPEN_LIGHT: "Слегка",
    SHARPEN_STRONG: "Заметно",
}

#: Пропорции кадра: ключ, подпись, (ширина, высота).
#: Список намеренно длинный и симметричный — вертикали и горизонтали парами.
ASPECT_RATIOS: list[tuple[str, str, tuple[int, int] | None]] = [
    ("free", "Свободно", None),
    ("1:1", "1:1 · квадрат", (1, 1)),
    ("4:5", "4:5 · вертикаль", (4, 5)),
    ("3:4", "3:4 · вертикаль", (3, 4)),
    ("2:3", "2:3 · вертикаль", (2, 3)),
    ("5:7", "5:7 · вертикаль", (5, 7)),
    ("3:5", "3:5 · вертикаль", (3, 5)),
    ("10:16", "10:16 · вертикаль", (10, 16)),
    ("9:16", "9:16 · вертикаль", (9, 16)),
    ("1:2", "1:2 · вертикаль", (1, 2)),
    ("9:21", "9:21 · вертикаль", (9, 21)),
    ("5:4", "5:4 · горизонталь", (5, 4)),
    ("4:3", "4:3 · горизонталь", (4, 3)),
    ("3:2", "3:2 · горизонталь", (3, 2)),
    ("7:5", "7:5 · горизонталь", (7, 5)),
    ("5:3", "5:3 · горизонталь", (5, 3)),
    ("16:10", "16:10 · горизонталь", (16, 10)),
    ("16:9", "16:9 · горизонталь", (16, 9)),
    ("2:1", "2:1 · горизонталь", (2, 1)),
    ("21:9", "21:9 · горизонталь", (21, 9)),
]

ASPECT_BY_KEY = {key: value for key, _, value in ASPECT_RATIOS}

THEME_DARK = "dark"
THEME_LIGHT = "light"


@dataclass
class Settings:
    """Полный набор параметров обработки."""

    # --- Целевой вес -----------------------------------------------------
    limit_enabled: bool = True
    target_mb: float = 5.0
    #: Целимся чуть ниже заявленного лимита: площадки считают мегабайт
    #: по-разному, а 2% запаса стоят копеек по качеству.
    safety_margin: float = 0.02

    # --- Режим и качество ------------------------------------------------
    mode: str = MODE_SMART
    quality: int = 92
    min_quality: int = 70

    # --- Разрешение ------------------------------------------------------
    exact_size_enabled: bool = False
    exact_width: int = 2000
    exact_height: int = 2666
    link_sides: bool = True
    aspect_ratio: str = "free"
    fit_mode: str = FIT_COVER
    crop_anchor: str = "center"
    pad_mode: str = PAD_WHITE
    pad_color: str = "#FFFFFF"
    allow_upscale: bool = True

    max_side_enabled: bool = True
    max_side: int = 2400
    min_side_enabled: bool = True
    min_side: int = 1200
    allow_downscale: bool = True

    # --- Формат, цвет, метаданные ---------------------------------------
    output_format: str = "auto"
    keep_metadata: bool = False
    convert_to_srgb: bool = True
    progressive: bool = True
    subsampling: str = "auto"  # auto | 444 | 422 | 420
    sharpen: str = SHARPEN_LIGHT

    # --- Выгрузка --------------------------------------------------------
    output_dir: str = ""
    keep_structure: bool = True
    copy_when_already_small: bool = True
    on_conflict: str = CONFLICT_SUFFIX
    name_suffix: str = ""
    rename_enabled: bool = False
    rename_pattern: str = "{name}"
    rename_start: int = 1

    # --- Прочее ----------------------------------------------------------
    theme: str = THEME_DARK
    threads: int = 0  # 0 = определить по числу ядер

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

    @property
    def exact_size(self) -> tuple[int, int] | None:
        """Требуемый размер в пикселях, если он задан."""
        if not self.exact_size_enabled:
            return None
        return (self.exact_width, self.exact_height)

    def normalized(self) -> "Settings":
        """Приводит взаимозависимые поля в согласованное состояние."""
        copy = Settings(**asdict(self))
        copy.quality = max(1, min(100, copy.quality))
        copy.min_quality = max(1, min(copy.quality, copy.min_quality))
        copy.max_side = max(64, copy.max_side)
        copy.min_side = max(16, min(copy.min_side, copy.max_side))
        copy.exact_width = max(1, min(20000, copy.exact_width))
        copy.exact_height = max(1, min(20000, copy.exact_height))
        copy.target_mb = max(0.05, copy.target_mb)
        copy.rename_start = max(0, copy.rename_start)

        if copy.exact_size_enabled:
            # Точный размер сам определяет разрешение — ограничения по стороне
            # тут только мешали бы, а «уменьшать сильнее» противоречило бы
            # обещанию отдать ровно заданные пиксели.
            copy.max_side_enabled = False
            copy.allow_downscale = False
        if copy.mode == MODE_LOSSLESS:
            # Любое изменение геометрии — это уже потеря.
            copy.allow_downscale = False
            copy.max_side_enabled = False
            copy.exact_size_enabled = False
        return copy

    def resized_by_ratio(self, changed: str) -> tuple[int, int]:
        """Пересчитывает вторую сторону под выбранные пропорции.

        `changed` — какую сторону только что правил пользователь.
        """
        ratio = ASPECT_BY_KEY.get(self.aspect_ratio)
        if ratio is None:
            return (self.exact_width, self.exact_height)
        wide, high = ratio
        if changed == "width":
            return (self.exact_width, max(1, round(self.exact_width * high / wide)))
        return (max(1, round(self.exact_height * wide / high)), self.exact_height)

    # --- Сериализация ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    @staticmethod
    def config_dir() -> Path:
        import os

        base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
        return Path(base) / "ImgFitter"

    @classmethod
    def config_path(cls) -> Path:
        return cls.config_dir() / "settings.json"

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
        try:
            return cls.from_dict(json.loads(cls.config_path().read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return cls()


#: Поля, которые сбрасывает кнопка возле размеров.
SIZE_FIELDS = (
    "exact_size_enabled", "exact_width", "exact_height", "link_sides",
    "aspect_ratio", "fit_mode", "crop_anchor", "pad_mode", "pad_color",
    "allow_upscale", "max_side_enabled", "max_side", "min_side_enabled",
    "min_side", "allow_downscale",
)


def reset_size_fields(settings: Settings) -> Settings:
    """Возвращает настройки с заводскими значениями всех полей размера."""
    defaults = Settings()
    for name in SIZE_FIELDS:
        setattr(settings, name, getattr(defaults, name))
    return settings


class Profiles:
    """Именованные наборы настроек — чтобы у команды они совпадали.

    Хранятся отдельным файлом рядом с настройками: его можно переслать
    коллеге, и у всех будут одни и те же цифры.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or Settings.config_dir() / "profiles.json"
        self._items: dict[str, dict[str, Any]] = {}
        self.load()

    def names(self) -> list[str]:
        return sorted(self._items, key=str.lower)

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self._items = {
            str(name): value
            for name, value in (data or {}).items()
            if isinstance(value, dict)
        }

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def get(self, name: str) -> Settings | None:
        data = self._items.get(name)
        return Settings.from_dict(data) if data else None

    def put(self, name: str, settings: Settings) -> None:
        stored = settings.to_dict()
        # Путь выгрузки и тема — про рабочее место, а не про профиль:
        # переслав профиль коллеге, вы бы утащили к нему свою папку.
        for key in ("output_dir", "theme"):
            stored.pop(key, None)
        self._items[name] = stored
        self.save()

    def remove(self, name: str) -> None:
        if self._items.pop(name, None) is not None:
            self.save()

    def export_to(self, path: Path) -> None:
        path.write_text(
            json.dumps(self._items, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def import_from(self, path: Path) -> list[str]:
        """Добавляет профили из файла, возвращает имена принятых."""
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("файл не похож на набор профилей")
        added = []
        for name, value in data.items():
            if isinstance(value, dict):
                self._items[str(name)] = value
                added.append(str(name))
        if added:
            self.save()
        return added
