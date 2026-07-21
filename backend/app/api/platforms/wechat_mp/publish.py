from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User, WechatMpPublishJob
from backend.app.schemas.wechat_mp import WechatMpPublishStatus
from backend.app.services.wechat_mp_publish_service import (
    WechatMpPublishValidationError,
    cancel_publish_job,
    poll_publish_job,
    submit_publish_job,
)


router = APIRouter(prefix="/platforms/wechat-mp", tags=["wechat-mp-publish"])


class WechatMpPublishRequest(BaseModel):
    confirm: bool = False
    scheduled_at: datetime | None = None

    @field_validator("scheduled_at")
    @classmethod
    def normalize_scheduled_at_to_utc_storage(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)


class WechatMpPublishJobResponse(BaseModel):
    id: int
    user_id: int
    account_id: int
    article_id: int
    draft_sync_id: int
    publish_id: str
    status: WechatMpPublishStatus
    scheduled_at: datetime | None
    raw_response: dict
    error_message: str
    created_at: datetime
    updated_at: datetime

    @field_validator("scheduled_at")
    @classmethod
    def expose_scheduled_at_as_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    model_config = {"from_attributes": True}


@router.get("/publish-jobs", response_model=list[WechatMpPublishJobResponse])
def list_publish_jobs(
    article_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(WechatMpPublishJob).where(WechatMpPublishJob.user_id == current_user.id)
    if article_id is not None:
        query = query.where(WechatMpPublishJob.article_id == article_id)
    return db.scalars(query.order_by(WechatMpPublishJob.id.desc())).all()


@router.post("/articles/{article_id}/publish", response_model=WechatMpPublishJobResponse, status_code=status.HTTP_201_CREATED)
def submit_publish(
    article_id: int,
    payload: WechatMpPublishRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not payload.confirm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Publish confirmation is required")
    try:
        return submit_publish_job(db, current_user.id, article_id, payload.scheduled_at)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WechatMpPublishValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (WechatMpApiError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="WeChat MP publish failed") from exc


@router.post("/publish-jobs/{job_id}/poll", response_model=WechatMpPublishJobResponse)
def poll_publish(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return poll_publish_job(db, current_user.id, job_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WechatMpPublishValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (WechatMpApiError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="WeChat MP publish status check failed") from exc


@router.post("/publish-jobs/{job_id}/cancel", response_model=WechatMpPublishJobResponse)
def cancel_publish(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return cancel_publish_job(db, current_user.id, job_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WechatMpPublishValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
