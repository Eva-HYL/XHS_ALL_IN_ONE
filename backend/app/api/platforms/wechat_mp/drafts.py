from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User, WechatMpArticle, WechatMpDraftSync
from backend.app.schemas.wechat_mp import WechatMpDraftSyncStatus
from backend.app.services.wechat_mp_layout_service import normalize_wechat_layout_style
from backend.app.services.wechat_mp_draft_service import WechatMpDraftValidationError, sync_article_to_wechat_draft


router = APIRouter(prefix="/platforms/wechat-mp/articles", tags=["wechat-mp-drafts"])


class WechatMpDraftSyncRequest(BaseModel):
    account_id: int = Field(gt=0)
    layout_style: str = Field(default="classic", min_length=1, max_length=64)


class WechatMpDraftSyncResponse(BaseModel):
    id: int
    user_id: int
    account_id: int
    article_id: int
    wechat_media_id: str
    article_revision: int
    status: WechatMpDraftSyncStatus
    raw_response: dict
    error_message: str
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/{article_id}/draft-syncs/latest", response_model=WechatMpDraftSyncResponse)
def get_latest_draft_sync(
    article_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    article = db.scalar(select(WechatMpArticle).where(
        WechatMpArticle.id == article_id,
        WechatMpArticle.user_id == current_user.id,
    ))
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP article not found")
    draft_sync = db.scalar(
        select(WechatMpDraftSync)
        .where(
            WechatMpDraftSync.article_id == article.id,
            WechatMpDraftSync.user_id == current_user.id,
        )
        .order_by(WechatMpDraftSync.id.desc())
    )
    if draft_sync is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP draft sync not found")
    return draft_sync


@router.post("/{article_id}/sync-draft", response_model=WechatMpDraftSyncResponse, status_code=status.HTTP_201_CREATED)
def sync_draft(
    article_id: int,
    payload: WechatMpDraftSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        layout_style = normalize_wechat_layout_style(payload.layout_style)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        return sync_article_to_wechat_draft(
            db=db,
            user_id=current_user.id,
            article_id=article_id,
            account_id=payload.account_id,
            layout_style=layout_style,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WechatMpDraftValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WechatMpApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "WeChat draft sync failed", "errcode": exc.errcode, "payload": exc.payload},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
