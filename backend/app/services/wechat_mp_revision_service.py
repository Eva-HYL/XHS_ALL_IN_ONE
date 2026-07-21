from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import WechatMpArticle, WechatMpDraftSync


def invalidate_synced_drafts(db: Session, article: WechatMpArticle, *, next_status: str) -> None:
    article.revision += 1
    article.status = next_status
    for draft_sync in db.scalars(
        select(WechatMpDraftSync).where(
            WechatMpDraftSync.article_id == article.id,
            WechatMpDraftSync.status == "synced",
        )
    ):
        draft_sync.status = "stale"
