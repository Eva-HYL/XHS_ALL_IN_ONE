from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.models import UsageRecord
from backend.app.services.pricing_service import (
    calculate_image_cost,
    calculate_text_cost,
    get_pricing,
)


def record_text_usage(
    *,
    db: Session,
    user_id: int,
    pipeline_run_id: str | None,
    step: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    platform: str | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    commit: bool = True,
) -> UsageRecord:
    cost = calculate_text_cost(model, input_tokens, output_tokens)
    snapshot = get_pricing()["text_models"][model]
    rec = UsageRecord(
        user_id=user_id,
        pipeline_run_id=pipeline_run_id,
        platform=platform,
        resource_type=resource_type,
        resource_id=resource_id,
        step=step,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        image_count=None,
        unit_price_snapshot=dict(snapshot),
        cost_yuan=cost,
    )
    db.add(rec)
    if commit:
        db.commit()
        db.refresh(rec)
    return rec


def record_image_usage(
    *,
    db: Session,
    user_id: int,
    pipeline_run_id: str | None,
    step: str,
    model: str,
    image_count: int,
) -> UsageRecord:
    cost = calculate_image_cost(model, image_count)
    snapshot = get_pricing()["image_models"][model]
    rec = UsageRecord(
        user_id=user_id,
        pipeline_run_id=pipeline_run_id,
        step=step,
        model=model,
        input_tokens=None,
        output_tokens=None,
        image_count=image_count,
        unit_price_snapshot=dict(snapshot),
        cost_yuan=cost,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec
