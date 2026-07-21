from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiAdapter
from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
from backend.app.models import WechatMpAccount, WechatMpArticle, WechatMpAsset, WechatMpDraftSync, WechatMpPublishJob
from backend.app.services.wechat_mp_crypto_service import decrypt_secret
from backend.app.services.wechat_mp_token_service import get_cached_access_token, normalize_token_cache

class WechatMpDraftValidationError(ValueError):
    pass


def _get_access_token(account: WechatMpAccount, adapter: WechatMpApiAdapter) -> str:
    token = get_cached_access_token(account.token_cache)
    if token is not None:
        return token

    payload = adapter.get_access_token(app_id=account.app_id, app_secret=decrypt_secret(account.encrypted_app_secret))
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("WeChat MP access token response is missing access_token")
    account.token_cache = normalize_token_cache(payload)
    return token


def _draft_active_key(account_id: int, article_id: int, article_revision: int) -> str:
    return f"account:{account_id}:article:{article_id}:revision:{article_revision}"


def _record_draft_failure(
    db: Session,
    draft_sync: WechatMpDraftSync,
    exc: Exception,
    *,
    indeterminate: bool,
) -> None:
    draft_sync.status = "pending" if indeterminate else "failed"
    if not indeterminate:
        draft_sync.active_key = None
    draft_sync.raw_response = exc.payload if isinstance(exc, WechatMpApiError) else {"error": str(exc)}
    draft_sync.error_message = str(exc)
    db.commit()


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
    ).order_by(WechatMpAsset.id.desc())).all()
    cover = next((asset for asset in assets if asset.role == "cover"), None)
    if cover is None:
        raise WechatMpDraftValidationError("WeChat MP article requires a generated cover image")
    if "{{image:" in article.html_body:
        raise WechatMpDraftValidationError("WeChat MP article still contains unresolved image placeholders")
    known_urls = {asset.public_url for asset in assets}
    local_urls = set(re.findall(r'src=["\'](/api/files/media/[^"\']+)["\']', article.html_body))
    if local_urls - known_urls:
        raise WechatMpDraftValidationError("WeChat MP article contains missing local assets")
    for asset in assets:
        if (asset.role == "cover" or asset.public_url in article.html_body) and not Path(asset.file_path).is_file():
            raise WechatMpDraftValidationError("WeChat MP article contains missing local asset files")
    active_key = _draft_active_key(account.id, article.id, article.revision)
    existing_pending = db.scalar(select(WechatMpDraftSync).where(
        WechatMpDraftSync.active_key == active_key,
        WechatMpDraftSync.status == "pending",
    ))
    if existing_pending is not None:
        raise WechatMpDraftValidationError("A WeChat MP draft sync is already pending reconciliation")

    draft_sync = WechatMpDraftSync(
        user_id=user_id,
        account_id=account.id,
        article_id=article.id,
        article_revision=article.revision,
        wechat_media_id="",
        active_key=active_key,
        status="pending",
        raw_response={},
    )
    db.add(draft_sync)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_pending = db.scalar(select(WechatMpDraftSync).where(
            WechatMpDraftSync.active_key == active_key,
            WechatMpDraftSync.status == "pending",
        ))
        if existing_pending is None:
            raise
        raise WechatMpDraftValidationError("A WeChat MP draft sync is already pending reconciliation")
    db.refresh(draft_sync)

    adapter = WechatMpApiAdapter()
    try:
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
    except Exception as exc:
        _record_draft_failure(db, draft_sync, exc, indeterminate=False)
        raise

    try:
        response = adapter.add_draft(access_token=access_token, article={
            "title": article.title,
            "digest": article.digest,
            "content": content,
            "thumb_media_id": thumb_media_id,
        })
        media_id = response.get("media_id")
        if not isinstance(media_id, str) or not media_id:
            raise ValueError("WeChat MP draft response is missing media_id")
    except Exception as exc:
        definitive_rejection = isinstance(exc, WechatMpApiError) and exc.is_definitive_rejection
        _record_draft_failure(db, draft_sync, exc, indeterminate=not definitive_rejection)
        raise

    for previous in db.scalars(select(WechatMpDraftSync).where(
        WechatMpDraftSync.article_id == article.id,
        WechatMpDraftSync.status == "synced",
        WechatMpDraftSync.id != draft_sync.id,
    )):
        previous.status = "stale"
    rebindable_draft_sync_ids = select(WechatMpDraftSync.id).where(
        WechatMpDraftSync.article_id == article.id,
        WechatMpDraftSync.article_revision == draft_sync.article_revision,
    )
    db.execute(
        update(WechatMpPublishJob)
        .where(
            WechatMpPublishJob.user_id == user_id,
            WechatMpPublishJob.account_id == account.id,
            WechatMpPublishJob.article_id == article.id,
            WechatMpPublishJob.status == "scheduled",
            WechatMpPublishJob.draft_sync_id.in_(rebindable_draft_sync_ids),
        )
        .values(draft_sync_id=draft_sync.id)
    )
    draft_sync.wechat_media_id = media_id
    draft_sync.status = "synced"
    draft_sync.active_key = None
    draft_sync.raw_response = response
    article.account_id = account.id
    article.status = "synced_to_wechat"
    db.commit()
    db.refresh(draft_sync)
    return draft_sync
