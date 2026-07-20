from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import ModelConfig, UsageRecord
from backend.app.services.pricing_service import get_pricing


@dataclass(frozen=True)
class ModelQuotaStatus:
    config: ModelConfig
    used_units: int
    free_ceiling: int
    free_remaining: int
    priority: int
    unit_price: Decimal
    capabilities: tuple[str, ...]

    def serialize(self) -> dict:
        return {
            "model_config_id": self.config.id,
            "model_type": self.config.model_type,
            "model": self.config.model_name,
            "is_default": self.config.is_default,
            "used_units": self.used_units,
            "free_ceiling": self.free_ceiling,
            "free_remaining": self.free_remaining,
            "priority": self.priority,
            "unit_price_yuan": str(self.unit_price),
            "capabilities": list(self.capabilities),
        }


def _usage_by_model(db: Session, user_id: int) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    rows = db.scalars(select(UsageRecord).where(UsageRecord.user_id == user_id)).all()
    for row in rows:
        bucket = result.setdefault(row.model, {"tokens": 0, "images": 0})
        bucket["tokens"] += (row.input_tokens or 0) + (row.output_tokens or 0)
        bucket["images"] += row.image_count or 0
    return result


def get_model_quota_statuses(db: Session, user_id: int, model_type: str | None = None) -> list[ModelQuotaStatus]:
    stmt = select(ModelConfig).where(ModelConfig.user_id == user_id)
    if model_type is not None:
        stmt = stmt.where(ModelConfig.model_type == model_type)
    configs = db.scalars(stmt).all()
    pricing = get_pricing()
    usage = _usage_by_model(db, user_id)
    statuses: list[ModelQuotaStatus] = []
    for config in configs:
        section = pricing.get(f"{config.model_type}_models", {})
        details = section.get(config.model_name)
        if not details:
            continue
        is_text = config.model_type == "text"
        ceiling = int(details.get("free_tokens" if is_text else "free_images", 0))
        used = usage.get(config.model_name, {}).get("tokens" if is_text else "images", 0)
        if is_text:
            unit_price = Decimal(str(details["input_yuan_per_million_tokens"]))
        else:
            unit_price = Decimal(str(details["yuan_per_image"]))
        statuses.append(ModelQuotaStatus(
            config=config,
            used_units=used,
            free_ceiling=ceiling,
            free_remaining=max(ceiling - used, 0),
            priority=int(details.get("priority", 100)),
            unit_price=unit_price,
            capabilities=tuple(details.get("capabilities", [])),
        ))
    return statuses


def select_model_config(
    db: Session,
    user_id: int,
    model_type: str,
    capability: str,
    excluded_model_names: set[str] | None = None,
) -> ModelConfig:
    excluded = excluded_model_names or set()
    candidates = [
        status for status in get_model_quota_statuses(db, user_id, model_type)
        if status.config.model_name not in excluded and capability in status.capabilities
    ]
    if not candidates:
        stmt = select(ModelConfig).where(
            ModelConfig.user_id == user_id,
            ModelConfig.model_type == model_type,
            ModelConfig.is_default.is_(True),
        )
        fallback = db.scalars(stmt).first()
        if fallback is None or fallback.model_name in excluded:
            raise ValueError(f"No configured {model_type} model supports {capability}")
        return fallback
    candidates.sort(key=lambda item: (
        0 if item.free_remaining > 0 else 1,
        item.priority if item.free_remaining > 0 else (0 if item.config.is_default else 1000),
        item.unit_price,
        item.priority,
    ))
    return candidates[0].config


def is_quota_error(error: Exception) -> bool:
    message = str(error).lower()
    markers = (
        "quota", "rate limit", "rate_limit", "429", "余额不足", "额度", "insufficient",
        "access to model denied", "not eligible", "model not found",
    )
    return any(marker in message for marker in markers)
