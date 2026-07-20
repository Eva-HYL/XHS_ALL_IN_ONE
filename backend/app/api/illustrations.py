from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.config import get_settings
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text
from backend.app.models import Character, IllustrationAsset, IllustrationRun, ModelConfig, UsageRecord, User
from backend.app.schemas.common import paginated
from backend.app.schemas.illustrations import (
    GenerateIllustrationRequest,
    GenerateRunShotRequest,
    GenerateShotlistRequest,
    IllustrationRunCreateRequest,
    IllustrationRunUpdateRequest,
    ImportIllustrationAssetRequest,
)
from backend.app.services.illustration_image_service import generate_and_persist_illustration
from backend.app.services.illustration_shotlist_service import generate_shotlist
from backend.app.services.usage_recording_service import record_text_usage
from backend.app.services.model_selector_service import (
    get_model_quota_statuses,
    is_quota_error,
    select_model_config,
)

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


def _serialize_run(run: IllustrationRun) -> dict:
    return {
        "id": run.id,
        "character_id": run.character_id,
        "essay": run.essay,
        "instruction": run.instruction,
        "status": run.status,
        "core_thesis": run.core_thesis,
        "cognitive_anchors": run.cognitive_anchors or [],
        "shots": run.shots or [],
        "selected_shot_seqs": run.selected_shot_seqs or [],
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def _get_owned_run(db: Session, user_id: int, run_id: str) -> IllustrationRun:
    run = db.get(IllustrationRun, run_id)
    if run is None or run.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Illustration run not found")
    return run


@router.get("/model-quotas")
def list_model_quotas(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"items": [status.serialize() for status in get_model_quota_statuses(db, current_user.id)]}


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


@router.post("/assets/import", status_code=status.HTTP_201_CREATED)
def import_illustration_asset(
    payload: ImportIllustrationAssetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expected_prefix = f"xhs-upload-u{current_user.id}-"
    if Path(payload.file_name).name != payload.file_name or not payload.file_name.startswith(expected_prefix):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded image not found")
    file_path = Path(get_settings().storage_dir) / "media" / payload.file_name
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded image not found")
    if file_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".webp"} or file_path.stat().st_size > 20 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Character reference must be an image under 20MB")
    if payload.character_id is not None:
        character = db.get(Character, payload.character_id)
        if character is None or character.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    asset = IllustrationAsset(
        user_id=current_user.id,
        character_id=payload.character_id,
        role="character_anchor",
        prompt="Uploaded character reference",
        model="upload",
        size="original",
        reference_asset_ids=[],
        file_path=str(file_path.resolve()),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _serialize_asset(asset)


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

    capability = "reference_image" if payload.reference_asset_ids else "text_to_image"
    model_config = select_model_config(db, current_user.id, "image", capability)
    try:
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
            if not is_quota_error(exc):
                raise
            fallback = select_model_config(
                db, current_user.id, "image", capability,
                excluded_model_names={model_config.model_name},
            )
            asset = generate_and_persist_illustration(
                db=db,
                current_user=current_user,
                model_config=fallback,
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

    model_config = select_model_config(db, current_user.id, "text", "shotlist")
    api_key = decrypt_text(model_config.encrypted_api_key) if model_config.encrypted_api_key else ""
    try:
        try:
            parsed, usage = generate_shotlist(
                model_config=model_config,
                api_key=api_key,
                essay=payload.essay,
                ip_definition=character.ip_definition,
                extra_instruction=payload.instruction,
            )
        except ValueError as exc:
            if not is_quota_error(exc):
                raise
            model_config = select_model_config(
                db, current_user.id, "text", "shotlist",
                excluded_model_names={model_config.model_name},
            )
            api_key = decrypt_text(model_config.encrypted_api_key) if model_config.encrypted_api_key else ""
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


@router.post("/pipeline-runs", status_code=status.HTTP_201_CREATED)
def create_pipeline_run(
    payload: IllustrationRunCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run_id = f"illustration-{uuid4().hex}"
    parsed = generate_shotlist_endpoint(
        GenerateShotlistRequest(
            essay=payload.essay,
            character_id=payload.character_id,
            instruction=payload.instruction,
            pipeline_run_id=run_id,
        ),
        current_user,
        db,
    )
    run = IllustrationRun(
        id=run_id,
        user_id=current_user.id,
        character_id=payload.character_id,
        essay=payload.essay,
        instruction=payload.instruction,
        status="shotlist_ready",
        core_thesis=parsed["core_thesis"],
        cognitive_anchors=list(parsed["cognitive_anchors"]),
        shots=list(parsed["shots"]),
        selected_shot_seqs=[shot["seq"] for shot in parsed["shots"]],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return _serialize_run(run)


@router.get("/pipeline-runs")
def list_pipeline_runs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 20,
):
    runs = db.scalars(
        select(IllustrationRun)
        .where(IllustrationRun.user_id == current_user.id)
        .order_by(IllustrationRun.created_at.desc())
    ).all()
    return paginated([_serialize_run(run) for run in runs], page=page, page_size=page_size)


@router.get("/pipeline-runs/{run_id}")
def get_pipeline_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _serialize_run(_get_owned_run(db, current_user.id, run_id))


@router.patch("/pipeline-runs/{run_id}")
def update_pipeline_run(
    run_id: str,
    payload: IllustrationRunUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _get_owned_run(db, current_user.id, run_id)
    if payload.shots is not None:
        run.shots = list(payload.shots)
    if payload.selected_shot_seqs is not None:
        run.selected_shot_seqs = list(payload.selected_shot_seqs)
    db.commit()
    db.refresh(run)
    return _serialize_run(run)


@router.post("/pipeline-runs/{run_id}/shots/{shot_seq}/generate")
def generate_pipeline_run_shot(
    run_id: str,
    shot_seq: int,
    payload: GenerateRunShotRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _get_owned_run(db, current_user.id, run_id)
    if not any(int(shot.get("seq", -1)) == shot_seq for shot in (run.shots or [])):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shot not found")
    result = generate_image(
        GenerateIllustrationRequest(
            prompt=payload.prompt,
            size=payload.size,
            character_id=run.character_id,
            reference_asset_ids=payload.reference_asset_ids,
            role="illustration",
            pipeline_run_id=run.id,
            shot_seq=shot_seq,
        ),
        current_user,
        db,
    )
    shots = []
    for shot in run.shots or []:
        if int(shot.get("seq", -1)) == shot_seq:
            shot = {**shot, "asset_id": result["id"], "generation_status": "completed"}
        shots.append(shot)
    run.shots = shots
    run.status = "completed" if all(shot.get("asset_id") for shot in shots if shot.get("seq") in (run.selected_shot_seqs or [])) else "generating"
    db.commit()
    return {"run": _serialize_run(run), "asset": result}
