"""Настройки, которые пользователь меняет в диалоге «Настройки».

Хранятся отдельно от presets/lamoda.json: тот файл описывает правила
маркетплейса (холст, поля, пороги) и его вправе заменить только сам
маркетплейс. Диалог настроек не должен молча его переписывать — поэтому
пользовательские предпочтения (формат, качество, что делать с макро,
куда сохранять) живут в собственном файле рядом с exe.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Preset, app_dir

SETTINGS_FILENAME = "LamodaItemFitter.settings.json"


@dataclass
class UserSettings:
    format: str = "jpeg"
    jpeg_quality: int = 100
    suffix: str = "_lamodafit"
    suffix_on_folder: bool = False
    conflict_policy: str = "copy"
    cropped_policy: str = "passthrough"
    cropped_fit_mode: str = "contain"
    shadow_mode: str = "exclude"
    output_root: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "UserSettings":
        target = path or (app_dir() / SETTINGS_FILENAME)
        if not target.is_file():
            return cls()
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        try:
            return cls(**known)
        except TypeError:
            return cls()

    def save(self, path: Path | None = None) -> None:
        target = path or (app_dir() / SETTINGS_FILENAME)
        try:
            target.write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # не удалось сохранить настройки — не повод останавливать работу

    def apply(self, preset: Preset) -> Preset:
        """Накладывает сохранённые предпочтения на пресет с правилами маркетплейса."""
        output = preset.output.__class__(**{
            **preset.output.__dict__,
            "format": self.format,
            "jpeg_quality": self.jpeg_quality,
            "suffix": self.suffix,
            "suffix_on_folder": self.suffix_on_folder,
        })
        return preset.replace(
            output=output,
            cropped_policy=self.cropped_policy,
            cropped_fit_mode=self.cropped_fit_mode,
            shadow_mode=self.shadow_mode,
        )

    @classmethod
    def from_state(cls, preset: Preset, conflict_policy: str, output_root: Path | None) -> "UserSettings":
        return cls(
            format=preset.output.format,
            jpeg_quality=preset.output.jpeg_quality,
            suffix=preset.output.suffix,
            suffix_on_folder=preset.output.suffix_on_folder,
            conflict_policy=conflict_policy,
            cropped_policy=preset.cropped_policy,
            cropped_fit_mode=preset.cropped_fit_mode,
            shadow_mode=preset.shadow_mode,
            output_root=str(output_root) if output_root else "",
        )
