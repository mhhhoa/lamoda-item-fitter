"""Цветовые преобразования.

Вся математика пайплайна (деление на модель фона, декомпрессия кромки, смешивание)
обязана выполняться в ЛИНЕЙНОМ RGB. Если делить прямо в sRGB, гамма-кривая исказит
результат: ровный фон не сойдётся в чистый белый, а полутона отражения уедут.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms

__all__ = [
    "srgb_to_linear",
    "linear_to_srgb",
    "load_srgb",
    "save_jpeg",
    "rgb_to_lab",
    "delta_e_2000",
    "hex_to_rgb",
]

# Кэш sRGB-профиля: ImageCms.createProfile заметно медленнее, чем хочется в цикле по 350 кадрам.
_SRGB_PROFILE = None


def _srgb_profile():
    global _SRGB_PROFILE
    if _SRGB_PROFILE is None:
        _SRGB_PROFILE = ImageCms.createProfile("sRGB")
    return _SRGB_PROFILE


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    """sRGB [0,1] -> линейный RGB [0,1]. Кусочная функция по спецификации IEC 61966-2-1."""
    x = np.asarray(x, dtype=np.float32)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    """Линейный RGB [0,1] -> sRGB [0,1]. Обратная к srgb_to_linear."""
    x = np.clip(np.asarray(x, dtype=np.float32), 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1.0 / 2.4) - 0.055).astype(np.float32)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """'#FFFFFF' -> (255, 255, 255)."""
    v = value.strip().lstrip("#")
    if len(v) != 6:
        raise ValueError(f"Ожидался цвет в формате #RRGGBB, получено: {value!r}")
    return tuple(int(v[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def load_srgb(path: str | Path) -> tuple[np.ndarray, dict]:
    """Читает файл и возвращает (float32 RGB [0,1] в sRGB, метаданные).

    Если у файла есть встроенный ICC-профиль, отличный от sRGB (AdobeRGB, ProPhoto,
    Display P3), изображение конвертируется в sRGB — иначе цвет товара уедет ещё
    до начала обработки, и ΔE в отчёте будет врать.
    """
    img = Image.open(path)
    meta: dict = {"orig_mode": img.mode, "orig_size": img.size, "converted_profile": False}

    icc = img.info.get("icc_profile")
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            src_name = ImageCms.getProfileDescription(src).strip()
            meta["orig_profile"] = src_name
            if "srgb" not in src_name.lower():
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                img = ImageCms.profileToProfile(img, src, _srgb_profile(), outputMode="RGB")
                meta["converted_profile"] = True
        except Exception as exc:  # повреждённый профиль не должен ронять пакетный прогон
            meta["profile_error"] = str(exc)

    if img.mode != "RGB":
        img = img.convert("RGB")

    arr = np.asarray(img, dtype=np.uint8).astype(np.float32) / 255.0
    return arr, meta


def save_jpeg(
    path: str | Path,
    rgb: np.ndarray,
    quality: int = 95,
    max_bytes: int | None = None,
    subsampling: int = 0,
) -> int:
    """Сохраняет float32 sRGB [0,1] в JPEG с профилем sRGB и без EXIF.

    Если задан max_bytes, качество понижается ступенями, пока файл не влезет в лимит
    (Lamoda не принимает файлы больше 10 МБ). Возвращает итоговый размер в байтах.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.clip(np.asarray(rgb, dtype=np.float32), 0.0, 1.0)
    img = Image.fromarray(np.round(arr * 255.0).astype(np.uint8), mode="RGB")
    icc = ImageCms.ImageCmsProfile(_srgb_profile()).tobytes()

    for q in (quality, 92, 88, 84, 80, 75):
        buf = io.BytesIO()
        # subsampling=0 (4:4:4) — на мелких деталях вроде шнурков и строчки
        # хроматическое прореживание 4:2:0 даёт заметную грязь.
        img.save(buf, "JPEG", quality=q, subsampling=subsampling, icc_profile=icc, optimize=True)
        data = buf.getvalue()
        if max_bytes is None or len(data) <= max_bytes:
            path.write_bytes(data)
            return len(data)
        if q == quality:
            continue

    path.write_bytes(data)
    return len(data)


# --- ΔE2000 -----------------------------------------------------------------
# Нужен, чтобы численно доказать, что цвет товара не уплыл после обработки,
# и чтобы сверяться с эталонами подрядчика.

_M_RGB2XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float32,
)
_WHITE_D65 = np.array([0.95047, 1.00000, 1.08883], dtype=np.float32)


def rgb_to_lab(srgb: np.ndarray) -> np.ndarray:
    """sRGB [0,1] (..., 3) -> CIELAB (..., 3) при белой точке D65."""
    lin = srgb_to_linear(srgb)
    xyz = lin @ _M_RGB2XYZ.T
    xyz = xyz / _WHITE_D65

    eps = np.float32(216.0 / 24389.0)
    kappa = np.float32(24389.0 / 27.0)
    f = np.where(xyz > eps, np.cbrt(np.maximum(xyz, 1e-12)), (kappa * xyz + 16.0) / 116.0)

    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return np.stack([116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)], axis=-1).astype(
        np.float32
    )


def delta_e_2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 между двумя массивами Lab. Возвращает ΔE поэлементно.

    Порог восприятия: ΔE < 1 — неразличимо, ΔE < 3 — различимо только при прямом
    сравнении рядом, ΔE > 5 — явно другой цвет.
    """
    lab1 = np.asarray(lab1, dtype=np.float64)
    lab2 = np.asarray(lab2, dtype=np.float64)
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    C_bar = 0.5 * (C1 + C2)
    C_bar7 = C_bar**7
    G = 0.5 * (1.0 - np.sqrt(C_bar7 / (C_bar7 + 25.0**7)))

    a1p, a2p = (1.0 + G) * a1, (1.0 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0

    dLp = L2 - L1
    dCp = C2p - C1p

    dhp = h2p - h1p
    dhp = np.where(dhp > 180.0, dhp - 360.0, dhp)
    dhp = np.where(dhp < -180.0, dhp + 360.0, dhp)
    dhp = np.where(C1p * C2p == 0.0, 0.0, dhp)
    dHp = 2.0 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp / 2.0))

    Lp_bar = 0.5 * (L1 + L2)
    Cp_bar = 0.5 * (C1p + C2p)

    hsum = h1p + h2p
    hdiff = np.abs(h1p - h2p)
    hp_bar = np.where(
        C1p * C2p == 0.0,
        hsum,
        np.where(
            hdiff <= 180.0,
            0.5 * hsum,
            np.where(hsum < 360.0, 0.5 * (hsum + 360.0), 0.5 * (hsum - 360.0)),
        ),
    )

    T = (
        1.0
        - 0.17 * np.cos(np.radians(hp_bar - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * hp_bar))
        + 0.32 * np.cos(np.radians(3.0 * hp_bar + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * hp_bar - 63.0))
    )

    d_theta = 30.0 * np.exp(-(((hp_bar - 275.0) / 25.0) ** 2))
    Cp_bar7 = Cp_bar**7
    R_C = 2.0 * np.sqrt(Cp_bar7 / (Cp_bar7 + 25.0**7))
    S_L = 1.0 + (0.015 * (Lp_bar - 50.0) ** 2) / np.sqrt(20.0 + (Lp_bar - 50.0) ** 2)
    S_C = 1.0 + 0.045 * Cp_bar
    S_H = 1.0 + 0.015 * Cp_bar * T
    R_T = -np.sin(np.radians(2.0 * d_theta)) * R_C

    return np.sqrt(
        (dLp / S_L) ** 2
        + (dCp / S_C) ** 2
        + (dHp / S_H) ** 2
        + R_T * (dCp / S_C) * (dHp / S_H)
    ).astype(np.float32)
