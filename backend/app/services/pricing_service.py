from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml


@lru_cache(maxsize=1)
def get_pricing() -> dict:
    """Load pricing config from config/pricing.yaml, cached for process lifetime."""
    root = Path(__file__).resolve().parents[3]
    # …/backend/app/services/pricing_service.py -> …/backend/app/services -> …/backend/app -> …/backend -> repo root
    path = root / "config" / "pricing.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def calculate_text_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    pricing = get_pricing()
    models = pricing.get("text_models", {})
    if model not in models:
        raise KeyError(f"No text pricing for model {model!r}. Configured: {list(models)}")
    m = models[model]
    cost = (
        Decimal(str(input_tokens)) * Decimal(str(m["input_yuan_per_million_tokens"]))
        + Decimal(str(output_tokens)) * Decimal(str(m["output_yuan_per_million_tokens"]))
    ) / Decimal("1000000")
    return cost.quantize(Decimal("0.0001"))


def calculate_image_cost(model: str, image_count: int) -> Decimal:
    pricing = get_pricing()
    models = pricing.get("image_models", {})
    if model not in models:
        raise KeyError(f"No image pricing for model {model!r}. Configured: {list(models)}")
    cost = Decimal(str(image_count)) * Decimal(str(models[model]["yuan_per_image"]))
    return cost.quantize(Decimal("0.0001"))
