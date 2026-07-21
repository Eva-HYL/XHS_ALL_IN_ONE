from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User, WechatMpArticle
from backend.app.schemas.wechat_mp import WechatMpArticleCreateRequest, WechatMpArticleResponse
from backend.app.services.wechat_mp_layout_service import render_wechat_html
from backend.app.services.wechat_mp_writer_service import generate_wechat_article


router = APIRouter(prefix="/platforms/wechat-mp/articles", tags=["wechat-mp-articles"])
_WRITER_TEXT_MODEL = "qwen3.7-plus"


class WechatMpArticleUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    markdown_body: str | None = None
    html_body: str | None = None
    digest: str | None = Field(default=None, max_length=255)
    illustration_skill: str | None = Field(default=None, min_length=1, max_length=80)


def _get_owned_article(db: Session, current_user: User, article_id: int) -> WechatMpArticle:
    article = db.get(WechatMpArticle, article_id)
    if article is None or article.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP article not found")
    return article


@router.post("", response_model=WechatMpArticleResponse, status_code=status.HTTP_201_CREATED)
def create_article(payload: WechatMpArticleCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return generate_wechat_article(db=db, user_id=current_user.id, request=payload, text_model=_WRITER_TEXT_MODEL)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("", response_model=list[WechatMpArticleResponse])
def list_articles(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(WechatMpArticle).where(WechatMpArticle.user_id == current_user.id).order_by(WechatMpArticle.id.desc())).all()


@router.get("/{article_id}", response_model=WechatMpArticleResponse)
def get_article(article_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get_owned_article(db, current_user, article_id)


@router.patch("/{article_id}", response_model=WechatMpArticleResponse)
def update_article(article_id: int, payload: WechatMpArticleUpdateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    article = _get_owned_article(db, current_user, article_id)
    for field in ("title", "markdown_body", "html_body", "digest", "illustration_skill"):
        value = getattr(payload, field)
        if value is not None:
            setattr(article, field, value)
    if payload.markdown_body is not None and payload.html_body is None:
        article.html_body = render_wechat_html(payload.markdown_body, image_placeholders=[])
    db.commit()
    db.refresh(article)
    return article
