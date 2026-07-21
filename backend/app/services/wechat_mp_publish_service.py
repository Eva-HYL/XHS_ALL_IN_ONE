from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiAdapter
from backend.app.models import WechatMpAccount, WechatMpArticle, WechatMpDraftSync, WechatMpPublishJob
from backend.app.services.wechat_mp_draft_service import _get_access_token


class WechatMpPublishValidationError(ValueError):
    pass


def _get_owned_article(db: Session, user_id: int, article_id: int) -> WechatMpArticle:
    article = db.scalar(select(WechatMpArticle).where(WechatMpArticle.id == article_id, WechatMpArticle.user_id == user_id))
    if article is None:
        raise LookupError("WeChat MP article not found")
    return article


def _get_latest_synced_draft(db: Session, user_id: int, article_id: int) -> WechatMpDraftSync:
    draft_sync = db.scalar(
        select(WechatMpDraftSync)
        .where(
            WechatMpDraftSync.user_id == user_id,
            WechatMpDraftSync.article_id == article_id,
            WechatMpDraftSync.status == "synced",
        )
        .order_by(WechatMpDraftSync.id.desc())
    )
    if draft_sync is None:
        raise WechatMpPublishValidationError("WeChat MP article requires a synced draft")
    return draft_sync


def _get_owned_account(db: Session, user_id: int, account_id: int) -> WechatMpAccount:
    account = db.scalar(select(WechatMpAccount).where(WechatMpAccount.id == account_id, WechatMpAccount.user_id == user_id))
    if account is None:
        raise LookupError("WeChat MP account not found")
    return account


def submit_publish_job(
    db: Session,
    user_id: int,
    article_id: int,
    scheduled_at: datetime | None = None,
) -> WechatMpPublishJob:
    article = _get_owned_article(db, user_id, article_id)
    draft_sync = _get_latest_synced_draft(db, user_id, article_id)
    account = _get_owned_account(db, user_id, draft_sync.account_id)

    if scheduled_at is not None:
        job = WechatMpPublishJob(
            user_id=user_id,
            account_id=account.id,
            article_id=article_id,
            draft_sync_id=draft_sync.id,
            status="scheduled",
            scheduled_at=scheduled_at,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    adapter = WechatMpApiAdapter()
    response = adapter.submit_publish(
        access_token=_get_access_token(account, adapter),
        media_id=draft_sync.wechat_media_id,
    )
    publish_id = response.get("publish_id")
    if not isinstance(publish_id, str) or not publish_id:
        raise ValueError("WeChat MP publish response is missing publish_id")

    job = WechatMpPublishJob(
        user_id=user_id,
        account_id=account.id,
        article_id=article_id,
        draft_sync_id=draft_sync.id,
        publish_id=publish_id,
        status="submitted",
        raw_response=response,
    )
    db.add(job)
    article.status = "publish_pending"
    db.commit()
    db.refresh(job)
    return job


def _map_publish_status(response: dict) -> str:
    value = response.get("publish_status")
    if value in (0, "0", "published", "success"):
        return "published"
    if value in (1, "1", "publishing"):
        return "publishing"
    if value in (2, "2", 3, "3", 4, "4", 5, "5", 6, "6", "failed", "rejected"):
        return "failed"
    return "submitted"


def _failure_message(response: dict) -> str:
    for key in ("errmsg", "error_message", "fail_reason", "fail_idx"):
        value = response.get(key)
        if value not in (None, ""):
            return str(value)
    return "publish failed"


def poll_publish_job(db: Session, user_id: int, publish_job_id: int) -> WechatMpPublishJob:
    job = db.scalar(select(WechatMpPublishJob).where(WechatMpPublishJob.id == publish_job_id, WechatMpPublishJob.user_id == user_id))
    if job is None:
        raise LookupError("WeChat MP publish job not found")
    if not job.publish_id:
        raise WechatMpPublishValidationError("WeChat MP publish job has not been submitted")

    account = _get_owned_account(db, user_id, job.account_id)
    adapter = WechatMpApiAdapter()
    response = adapter.get_publish_status(access_token=_get_access_token(account, adapter), publish_id=job.publish_id)
    job.status = _map_publish_status(response)
    job.raw_response = response
    job.error_message = "" if job.status != "failed" else _failure_message(response)
    if job.status in {"published", "failed"}:
        article = _get_owned_article(db, user_id, job.article_id)
        article.status = "published" if job.status == "published" else "synced_to_wechat"
    db.commit()
    db.refresh(job)
    return job
