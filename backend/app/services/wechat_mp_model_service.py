from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import decrypt_text
from backend.app.models import ModelConfig
from backend.app.services.model_selector_service import select_model_config


@dataclass(frozen=True)
class WechatMpModelContext:
    model_name: str
    base_url: str
    api_key: str


def _to_model_context(config: ModelConfig) -> WechatMpModelContext:
    return WechatMpModelContext(
        model_name=config.model_name,
        base_url=config.base_url,
        api_key=decrypt_text(config.encrypted_api_key) if config.encrypted_api_key else "",
    )


def resolve_wechat_mp_shotlist_model(
    *, db: Session, user_id: int, excluded_model_names: set[str] | None = None,
) -> WechatMpModelContext:
    """Prefer the configured Qwen Max model before using the quota-aware selector."""
    excluded = excluded_model_names or set()
    if "qwen3.7-max" not in excluded:
        preferred = db.scalar(
            select(ModelConfig).where(
                ModelConfig.user_id == user_id,
                ModelConfig.model_type == "text",
                ModelConfig.model_name == "qwen3.7-max",
            )
        )
        if preferred is not None:
            return _to_model_context(preferred)
    return _to_model_context(select_model_config(
        db, user_id, "text", "shotlist", excluded_model_names=excluded,
    ))


def resolve_wechat_mp_model(
    *,
    db: Session,
    user_id: int,
    model_type: str,
    requested_model: str | None = None,
) -> WechatMpModelContext:
    configs = db.scalars(
        select(ModelConfig).where(
            ModelConfig.user_id == user_id,
            ModelConfig.model_type == model_type,
        )
    ).all()
    selected = None
    if requested_model:
        selected = next((item for item in configs if item.model_name == requested_model), None)
        if configs and selected is None:
            raise ValueError(f"Requested {model_type} model is not configured for this user")
    if selected is None:
        selected = next((item for item in configs if item.is_default), None) or (configs[0] if configs else None)
    if selected is not None:
        return _to_model_context(selected)

    prefix = "WECHAT_MP_IMAGE" if model_type == "image" else "WECHAT_MP_WRITER"
    fallback = requested_model or ("doubao-seedream-4-0-250828" if model_type == "image" else "qwen3.7-plus")
    return WechatMpModelContext(
        model_name=fallback,
        base_url=os.getenv(f"{prefix}_BASE_URL", "").rstrip("/"),
        api_key=os.getenv(f"{prefix}_API_KEY", ""),
    )
