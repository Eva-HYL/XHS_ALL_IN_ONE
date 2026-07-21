from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiAdapter, WechatMpApiError
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User, WechatMpAccount
from backend.app.schemas.wechat_mp import WechatMpAccountCreateRequest, WechatMpAccountResponse
from backend.app.services.wechat_mp_crypto_service import decrypt_secret, encrypt_secret
from backend.app.services.wechat_mp_token_service import normalize_token_cache

router = APIRouter(prefix="/platforms/wechat-mp/accounts", tags=["wechat-mp-accounts"])


def get_wechat_mp_api_adapter() -> WechatMpApiAdapter:
    return WechatMpApiAdapter()


def _get_owned_account(db: Session, current_user: User, account_id: int) -> WechatMpAccount:
    account = db.get(WechatMpAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP account not found")
    return account


@router.post("", response_model=WechatMpAccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: WechatMpAccountCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = WechatMpAccount(
        user_id=current_user.id,
        name=payload.name,
        app_id=payload.app_id,
        encrypted_app_secret=encrypt_secret(payload.app_secret),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("", response_model=list[WechatMpAccountResponse])
def list_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(WechatMpAccount)
        .where(WechatMpAccount.user_id == current_user.id)
        .order_by(WechatMpAccount.id.desc())
    ).all()


@router.post("/{account_id}/test", response_model=WechatMpAccountResponse)
def test_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: WechatMpApiAdapter = Depends(get_wechat_mp_api_adapter),
):
    account = _get_owned_account(db, current_user, account_id)
    try:
        account.token_cache = normalize_token_cache(adapter.get_access_token(
            app_id=account.app_id,
            app_secret=decrypt_secret(account.encrypted_app_secret),
        ))
        account.connection_status = "connected"
        db.commit()
        db.refresh(account)
    except WechatMpApiError as exc:
        account.connection_status = "error"
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="WeChat MP connection test failed") from exc
    return account
