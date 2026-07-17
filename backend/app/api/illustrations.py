from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import Character, IllustrationAsset, ModelConfig, User
from backend.app.schemas.illustrations import GenerateIllustrationRequest
from backend.app.services.illustration_image_service import generate_and_persist_illustration

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
    return _serialize_asset(asset)
