from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiAdapter, WechatMpApiError
from backend.app.models import WechatMpAccount, WechatMpArticle, WechatMpDraftSync, WechatMpPublishJob
from backend.app.services.wechat_mp_draft_service import _get_access_token


class WechatMpPublishValidationError(ValueError):
    pass


_ACTIVE_PUBLISH_STATUSES = ("scheduled", "pending", "submitted", "publishing")


def _publish_active_key(account_id: int, article_id: int, article_revision: int) -> str:
    return f"account:{account_id}:article:{article_id}:revision:{article_revision}"


def _get_active_publish_job(db: Session, active_key: str) -> WechatMpPublishJob | None:
    return db.scalar(
        select(WechatMpPublishJob)
        .where(
            WechatMpPublishJob.active_key == active_key,
            WechatMpPublishJob.status.in_(_ACTIVE_PUBLISH_STATUSES),
        )
        .order_by(WechatMpPublishJob.id)
    )


def _commit_new_publish_job(db: Session, job: WechatMpPublishJob) -> WechatMpPublishJob:
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _get_active_publish_job(db, job.active_key or "")
        if existing is None:
            raise
        return existing
    db.refresh(job)
    return job


def _get_owned_article(db: Session, user_id: int, article_id: int) -> WechatMpArticle:
    article = db.scalar(select(WechatMpArticle).where(WechatMpArticle.id == article_id, WechatMpArticle.user_id == user_id))
    if article is None:
        raise LookupError("WeChat MP article not found")
    return article


def _get_latest_synced_draft(db: Session, user_id: int, article: WechatMpArticle) -> WechatMpDraftSync:
    draft_sync = db.scalar(
        select(WechatMpDraftSync)
        .where(
            WechatMpDraftSync.user_id == user_id,
            WechatMpDraftSync.article_id == article.id,
            WechatMpDraftSync.status == "synced",
            WechatMpDraftSync.article_revision == article.revision,
        )
        .order_by(WechatMpDraftSync.id.desc())
    )
    if draft_sync is None:
        raise WechatMpPublishValidationError("WeChat MP article requires a current synced draft")
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
    draft_sync = _get_latest_synced_draft(db, user_id, article)
    account = _get_owned_account(db, user_id, draft_sync.account_id)
    active_key = _publish_active_key(account.id, article.id, draft_sync.article_revision)
    existing_active = _get_active_publish_job(db, active_key)
    if existing_active is not None:
        return existing_active

    if scheduled_at is not None:
        job = WechatMpPublishJob(
            user_id=user_id,
            account_id=account.id,
            article_id=article_id,
            draft_sync_id=draft_sync.id,
            active_key=active_key,
            status="scheduled",
            scheduled_at=scheduled_at,
        )
        return _commit_new_publish_job(db, job)

    job = WechatMpPublishJob(
        user_id=user_id,
        account_id=account.id,
        article_id=article_id,
        draft_sync_id=draft_sync.id,
        active_key=active_key,
        status="pending",
        raw_response={},
    )
    persisted_job = _commit_new_publish_job(db, job)
    if persisted_job is not job:
        return persisted_job
    return _submit_existing_job(db=db, job=persisted_job, article=article, account=account, adapter=WechatMpApiAdapter())


def _submit_existing_job(
    *, db: Session, job: WechatMpPublishJob, article: WechatMpArticle,
    account: WechatMpAccount, adapter: WechatMpApiAdapter,
) -> WechatMpPublishJob:
    draft_sync = db.get(WechatMpDraftSync, job.draft_sync_id)
    if (
        draft_sync is None
        or draft_sync.status != "synced"
        or draft_sync.article_revision != article.revision
    ):
        job.status = "failed"
        job.active_key = None
        job.error_message = "Scheduled publish draft is stale; sync the article again"
        db.commit()
        raise WechatMpPublishValidationError(job.error_message)

    try:
        access_token = _get_access_token(account, adapter)
    except Exception as exc:
        job.status = "failed"
        job.active_key = None
        job.raw_response = exc.payload if isinstance(exc, WechatMpApiError) else {"error": str(exc)}
        job.error_message = str(exc)
        db.commit()
        raise

    try:
        response = adapter.submit_publish(
            access_token=access_token,
            media_id=draft_sync.wechat_media_id,
        )
        publish_id = response.get("publish_id")
        if not isinstance(publish_id, str) or not publish_id:
            raise ValueError("WeChat MP publish response is missing publish_id")
    except Exception as exc:
        definitive_rejection = isinstance(exc, WechatMpApiError) and exc.is_definitive_rejection
        job.status = "failed" if definitive_rejection else "pending"
        if definitive_rejection:
            job.active_key = None
        job.raw_response = exc.payload if isinstance(exc, WechatMpApiError) else {"error": str(exc)}
        job.error_message = str(exc)
        db.commit()
        raise
    job.publish_id = publish_id
    job.status = "submitted"
    job.raw_response = response
    job.error_message = ""
    article.status = "publish_pending"
    db.commit()
    db.refresh(job)
    return job


def run_due_publish_jobs(*, db: Session, now: datetime, adapter_factory=WechatMpApiAdapter) -> dict:
    jobs = db.scalars(
        select(WechatMpPublishJob).where(
            WechatMpPublishJob.status == "scheduled",
            WechatMpPublishJob.scheduled_at.is_not(None),
            WechatMpPublishJob.scheduled_at <= now,
        ).order_by(WechatMpPublishJob.scheduled_at, WechatMpPublishJob.id)
    ).all()
    failed_count = 0
    items = []
    for job in jobs:
        draft_sync = db.get(WechatMpDraftSync, job.draft_sync_id)
        if draft_sync is None:
            job.status = "failed"
            job.active_key = None
            job.error_message = "Scheduled publish draft no longer exists"
            db.commit()
            failed_count += 1
            continue
        active_jobs = db.scalars(
            select(WechatMpPublishJob)
            .join(WechatMpDraftSync, WechatMpDraftSync.id == WechatMpPublishJob.draft_sync_id)
            .where(
                WechatMpPublishJob.account_id == job.account_id,
                WechatMpPublishJob.article_id == job.article_id,
                WechatMpDraftSync.article_revision == draft_sync.article_revision,
                WechatMpPublishJob.status.in_(_ACTIVE_PUBLISH_STATUSES),
            )
            .order_by(WechatMpPublishJob.id)
        ).all()
        canonical = active_jobs[0] if active_jobs else None
        if canonical is not None and canonical.id != job.id:
            job.status = "cancelled"
            job.active_key = None
            job.error_message = f"Duplicate active publish job; canonical job is #{canonical.id}"
            db.commit()
            continue
        claimed = db.execute(
            update(WechatMpPublishJob)
            .where(
                WechatMpPublishJob.id == job.id,
                WechatMpPublishJob.status == "scheduled",
            )
            .values(status="pending")
        ).rowcount
        db.commit()
        if claimed != 1:
            continue
        db.refresh(job)
        try:
            article = _get_owned_article(db, job.user_id, job.article_id)
            account = _get_owned_account(db, job.user_id, job.account_id)
            _submit_existing_job(
                db=db, job=job, article=article, account=account, adapter=adapter_factory(),
            )
        except Exception:
            failed_count += 1
        items.append(job)
    return {"executed_count": len(items), "failed_count": failed_count, "items": items}


def run_due_wechat_mp_publish_jobs_once() -> dict:
    from backend.app.core.database import SessionLocal

    db = SessionLocal()
    try:
        return run_due_publish_jobs(db=db, now=datetime.utcnow())
    finally:
        db.close()


def cancel_publish_job(db: Session, user_id: int, publish_job_id: int) -> WechatMpPublishJob:
    cancelled = db.execute(
        update(WechatMpPublishJob)
        .where(
            WechatMpPublishJob.id == publish_job_id,
            WechatMpPublishJob.user_id == user_id,
            WechatMpPublishJob.status == "scheduled",
        )
        .values(status="cancelled", active_key=None)
    )
    if cancelled.rowcount != 1:
        raise WechatMpPublishValidationError("Only scheduled WeChat MP publish jobs can be cancelled")
    db.commit()
    job = db.scalar(select(WechatMpPublishJob).where(
        WechatMpPublishJob.id == publish_job_id,
        WechatMpPublishJob.user_id == user_id,
    ))
    assert job is not None
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
        job.active_key = None
        article = _get_owned_article(db, user_id, job.article_id)
        article.status = "published" if job.status == "published" else "synced_to_wechat"
    db.commit()
    db.refresh(job)
    return job
