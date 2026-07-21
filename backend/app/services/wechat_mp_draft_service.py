from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiAdapter
from backend.app.models import WechatMpAccount, WechatMpArticle, WechatMpAsset, WechatMpDraftSync
from backend.app.services.wechat_mp_crypto_service import decrypt_secret


def _get_access_token(account: WechatMpAccount, adapter: WechatMpApiAdapter) -> str:
    cached = account.token_cache or {}
    token = cached.get("access_token")
    expires_at = cached.get("expires_at")
    if isinstance(token, str) and token and (not isinstance(expires_at, (int, float)) or expires_at > time.time()):
        return token

    payload = adapter.get_access_token(app_id=account.app_id, app_secret=decrypt_secret(account.encrypted_app_secret))
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("WeChat MP access token response is missing access_token")
    account.token_cache = {**payload, "expires_at": time.time() + max(int(payload.get("expires_in", 0)) - 60, 0)}
    return token


def sync_article_to_wechat_draft(db: Session, user_id: int, article_id: int, account_id: int) -> WechatMpDraftSync:
    article = db.scalar(select(WechatMpArticle).where(WechatMpArticle.id == article_id, WechatMpArticle.user_id == user_id))
    account = db.scalar(select(WechatMpAccount).where(WechatMpAccount.id == account_id, WechatMpAccount.user_id == user_id))
    if article is None:
        raise LookupError("WeChat MP article not found")
    if account is None:
        raise LookupError("WeChat MP account not found")

    assets = db.scalars(select(WechatMpAsset).where(
        WechatMpAsset.article_id == article.id,
        WechatMpAsset.user_id == user_id,
        WechatMpAsset.status == "generated",
    )).all()
    cover = next((asset for asset in assets if asset.role == "cover"), None)
    if cover is None:
        raise ValueError("WeChat MP article requires a generated cover image")

    adapter = WechatMpApiAdapter()
    access_token = _get_access_token(account, adapter)
    thumbnail = adapter.upload_permanent_image(access_token=access_token, file_path=cover.file_path)
    thumb_media_id = thumbnail.get("media_id")
    if not isinstance(thumb_media_id, str) or not thumb_media_id:
        raise ValueError("WeChat MP cover upload response is missing media_id")

    content = article.html_body
    for asset in assets:
        if asset.id == cover.id or asset.public_url not in content:
            continue
        uploaded = adapter.upload_content_image(access_token=access_token, file_path=asset.file_path)
        url = uploaded.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("WeChat MP content image upload response is missing url")
        content = content.replace(asset.public_url, url)

    response = adapter.add_draft(access_token=access_token, article={
        "title": article.title,
        "digest": article.digest,
        "content": content,
        "thumb_media_id": thumb_media_id,
    })
    media_id = response.get("media_id")
    if not isinstance(media_id, str) or not media_id:
        raise ValueError("WeChat MP draft response is missing media_id")

    draft_sync = WechatMpDraftSync(
        user_id=user_id,
        account_id=account.id,
        article_id=article.id,
        wechat_media_id=media_id,
        status="synced",
        raw_response=response,
    )
    article.account_id = account.id
    article.status = "synced_to_wechat"
    db.add(draft_sync)
    db.commit()
    db.refresh(draft_sync)
    return draft_sync
