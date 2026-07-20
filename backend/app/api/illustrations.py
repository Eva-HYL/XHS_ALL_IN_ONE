from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text
from backend.app.models import Character, IllustrationAsset, ModelConfig, UsageRecord, User
from backend.app.schemas.common import paginated
from backend.app.schemas.illustrations import GenerateIllustrationRequest, GenerateShotlistRequest
from backend.app.services.illustration_image_service import generate_and_persist_illustration
from backend.app.services.illustration_shotlist_service import generate_shotlist
from backend.app.services.usage_recording_service import record_text_usage

router = APIRouter(prefix="/illustrations", tags=["illustrations"])


def _default_image_model(db: Session, user: User) -> ModelConfig:
    cfg = db.scalars(
        select(ModelConfig).where(
            ModelConfig.user_id == user.id,
            ModelConfig.model_type == "image",
            ModelConfig.is_default.is_(True),
        )
    ).first()
    if cfg is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Default image model is not configured")
    return cfg


def _default_text_model(db: Session, user: User) -> tuple[ModelConfig, str]:
    cfg = db.scalars(
        select(ModelConfig).where(
            ModelConfig.user_id == user.id,
            ModelConfig.model_type == "text",
            ModelConfig.is_default.is_(True),
        )
    ).first()
    if cfg is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Default text model is not configured")
    api_key = decrypt_text(cfg.encrypted_api_key) if cfg.encrypted_api_key else ""
    return cfg, api_key


def _serialize_asset(asset: IllustrationAsset) -> dict:
    return {
        "id": asset.id,
        "user_id": asset.user_id,
        "character_id": asset.character_id,
        "role": asset.role,
        "pipeline_run_id": asset.pipeline_run_id,
        "shot_seq": asset.shot_seq,
        "prompt": asset.prompt,
        "model": asset.model,
        "size": asset.size,
        "reference_asset_ids": asset.reference_asset_ids or [],
        "file_path": asset.file_path,
        "created_at": asset.created_at.isoformat(),
    }


@router.get("/assets")
def list_illustration_assets(
    pipeline_run_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
):
    stmt = select(IllustrationAsset).where(IllustrationAsset.user_id == current_user.id)
    if pipeline_run_id is not None:
        stmt = stmt.where(IllustrationAsset.pipeline_run_id == pipeline_run_id)
    items = db.scalars(stmt.order_by(IllustrationAsset.id.desc())).all()
    return paginated([_serialize_asset(asset) for asset in items], page=page, page_size=page_size)


@router.get("/usage-summary")
def illustration_usage_summary(
    pipeline_run_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(UsageRecord).where(UsageRecord.user_id == current_user.id)
    if pipeline_run_id is not None:
        stmt = stmt.where(UsageRecord.pipeline_run_id == pipeline_run_id)
    rows = db.scalars(stmt.order_by(UsageRecord.id.asc())).all()
    total = sum((row.cost_yuan for row in rows), start=0)
    return {
        "pipeline_run_id": pipeline_run_id,
        "total_cost_yuan": f"{total:.4f}",
        "items": [
            {
                "step": row.step,
                "model": row.model,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "image_count": row.image_count,
                "cost_yuan": f"{row.cost_yuan:.4f}",
            }
            for row in rows
        ],
    }


@router.post("/generate-image")
def generate_image(
    payload: GenerateIllustrationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.character_id is not None:
        char = db.get(Character, payload.character_id)
        if char is None or char.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    model_config = _default_image_model(db, current_user)
    try:
        asset = generate_and_persist_illustration(
            db=db,
            current_user=current_user,
            model_config=model_config,
            prompt=payload.prompt,
            size=payload.size,
            reference_asset_ids=list(payload.reference_asset_ids),
            character_id=payload.character_id,
            role=payload.role,
            pipeline_run_id=payload.pipeline_run_id,
            shot_seq=payload.shot_seq,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return _serialize_asset(asset)


@router.post("/generate-shotlist")
def generate_shotlist_endpoint(
    payload: GenerateShotlistRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = db.get(Character, payload.character_id)
    if character is None or character.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    model_config, api_key = _default_text_model(db, current_user)
    try:
        parsed, usage = generate_shotlist(
            model_config=model_config,
            api_key=api_key,
            essay=payload.essay,
            ip_definition=character.ip_definition,
            extra_instruction=payload.instruction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    record_text_usage(
        db=db,
        user_id=current_user.id,
        pipeline_run_id=payload.pipeline_run_id,
        step="crack_and_shotlist",
        model=model_config.model_name,
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
    )
    return parsed
