from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User, WechatMpDraftSync
from backend.app.schemas.wechat_mp import WechatMpDraftSyncStatus
from backend.app.services.wechat_mp_draft_service import WechatMpDraftValidationError, sync_article_to_wechat_draft


router = APIRouter(prefix="/platforms/wechat-mp/articles", tags=["wechat-mp-drafts"])


class WechatMpDraftSyncRequest(BaseModel):
    account_id: int = Field(gt=0)


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


@router.post("/{article_id}/sync-draft", response_model=WechatMpDraftSyncResponse, status_code=status.HTTP_201_CREATED)
def sync_draft(
    article_id: int,
    payload: WechatMpDraftSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return sync_article_to_wechat_draft(db=db, user_id=current_user.id, article_id=article_id, account_id=payload.account_id)
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
