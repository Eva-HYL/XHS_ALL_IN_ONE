from __future__ import annotations

import re


_DOUBAO_PRESETS = {
    "3:4": "1728x2304",
    "4:3": "2304x1728",
    "1:1": "2048x2048",
    "9:16": "1536x2732",
    "16:9": "2732x1536",
}


def normalize_illustration_size(model_name: str, requested: str) -> str:
    """Translate UI aspect-ratio aliases into provider-legal pixel sizes."""
    value = requested.strip().lower()
    if re.fullmatch(r"\d{3,5}x\d{3,5}", value):
        return value
    if model_name.startswith("doubao-seedream"):
        try:
            return _DOUBAO_PRESETS[value]
        except KeyError as exc:
            supported = ", ".join(_DOUBAO_PRESETS)
            raise ValueError(f"Unsupported Doubao illustration size '{requested}'; use {supported} or WIDTHxHEIGHT") from exc
    return requested
