from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User, WechatMpArticle, WechatMpArticleSection, WechatMpImagePrompt
from backend.app.schemas.wechat_mp import WechatMpArticleCreateRequest, WechatMpArticleResponse, WechatMpAssetResponse, WechatMpImagePromptResponse
from backend.app.services.wechat_mp_image_service import (
    WechatMpImageValidationError,
    generate_asset_for_prompt,
    generate_cover_asset,
)
from backend.app.services.wechat_mp_image_prompt_service import (
    _restore_prompt_placeholder,
    generate_image_prompts,
    regenerate_image_prompt,
)
from backend.app.services.wechat_mp_layout_service import render_wechat_html
from backend.app.services.wechat_mp_writer_service import generate_wechat_article


router = APIRouter(prefix="/platforms/wechat-mp/articles", tags=["wechat-mp-articles"])
image_router = APIRouter(prefix="/platforms/wechat-mp", tags=["wechat-mp-assets"])


class WechatMpArticleUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    markdown_body: str | None = None
    html_body: str | None = None
    digest: str | None = Field(default=None, max_length=255)
    illustration_skill: str | None = Field(default=None, min_length=1, max_length=80)


class WechatMpPromptGenerateRequest(BaseModel):
    skill_name: str | None = Field(default=None, min_length=1, max_length=80)


class WechatMpPromptUpdateRequest(BaseModel):
    editable_prompt: str = Field(min_length=1)


class WechatMpImageGenerateRequest(BaseModel):
    image_model: str | None = Field(default=None, min_length=1, max_length=128)
    size: str = Field(default="16:9", min_length=1, max_length=32)


def _get_owned_article(db: Session, current_user: User, article_id: int) -> WechatMpArticle:
    article = db.get(WechatMpArticle, article_id)
    if article is None or article.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP article not found")
    return article


def _get_owned_prompt(db: Session, article: WechatMpArticle, prompt_id: int) -> WechatMpImagePrompt:
    prompt = db.get(WechatMpImagePrompt, prompt_id)
    if prompt is None or prompt.article_id != article.id or prompt.user_id != article.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP prompt not found")
    return prompt


@router.post("", response_model=WechatMpArticleResponse, status_code=status.HTTP_201_CREATED)
def create_article(payload: WechatMpArticleCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return generate_wechat_article(db=db, user_id=current_user.id, request=payload)
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
    from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts

    article = _get_owned_article(db, current_user, article_id)
    changed = False
    for field in ("title", "markdown_body", "html_body", "digest", "illustration_skill"):
        value = getattr(payload, field)
        if value is not None and value != getattr(article, field):
            setattr(article, field, value)
            changed = True
    if payload.markdown_body is not None and payload.html_body is None:
        article.html_body = render_wechat_html(payload.markdown_body, image_placeholders=[])
    if changed:
        invalidate_synced_drafts(db, article, next_status="layout_ready")
    db.commit()
    db.refresh(article)
    return article


@router.post("/{article_id}/prompts", response_model=list[WechatMpImagePromptResponse], status_code=status.HTTP_201_CREATED)
def create_prompts(
    article_id: int,
    payload: WechatMpPromptGenerateRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    article = _get_owned_article(db, current_user, article_id)
    try:
        return generate_image_prompts(
            db=db,
            user_id=current_user.id,
            article_id=article.id,
            skill_name=payload.skill_name if payload else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/{article_id}/prompts", response_model=list[WechatMpImagePromptResponse])
def list_prompts(
    article_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    article = _get_owned_article(db, current_user, article_id)
    return db.scalars(
        select(WechatMpImagePrompt)
        .where(WechatMpImagePrompt.article_id == article.id, WechatMpImagePrompt.user_id == current_user.id)
        .order_by(WechatMpImagePrompt.section_id, WechatMpImagePrompt.id)
    ).all()


@router.patch("/{article_id}/prompts/{prompt_id}", response_model=WechatMpImagePromptResponse)
def update_prompt(
    article_id: int,
    prompt_id: int,
    payload: WechatMpPromptUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    article = _get_owned_article(db, current_user, article_id)
    prompt = _get_owned_prompt(db, article, prompt_id)
    section = db.get(WechatMpArticleSection, prompt.section_id)
    if section is None or section.article_id != article.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP prompt not found")
    prompt.editable_prompt = payload.editable_prompt
    prompt.version += 1
    prompt.status = "prompt_ready"
    _restore_prompt_placeholder(db, article, section, prompt)
    from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts
    invalidate_synced_drafts(db, article, next_status="prompts_ready")
    db.commit()
    db.refresh(prompt)
    return prompt


@image_router.post("/prompts/{prompt_id}/image", response_model=WechatMpAssetResponse, status_code=status.HTTP_201_CREATED)
def generate_image(
    prompt_id: int,
    payload: WechatMpImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return generate_asset_for_prompt(
            db=db,
            user_id=current_user.id,
            prompt_id=prompt_id,
            image_model=payload.image_model,
            size=payload.size,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WechatMpImageValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@image_router.get("/image-cost-estimate")
def image_cost_estimate(
    image_model: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from backend.app.services.wechat_mp_cost_service import estimate_image_action
    from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model

    try:
        model = resolve_wechat_mp_model(
            db=db, user_id=current_user.id, model_type="image", requested_model=image_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return estimate_image_action(model.model_name)


@router.post("/{article_id}/cover", response_model=WechatMpAssetResponse, status_code=status.HTTP_201_CREATED)
def generate_cover(
    article_id: int,
    payload: WechatMpImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_article(db, current_user, article_id)
    try:
        return generate_cover_asset(
            db=db, user_id=current_user.id, article_id=article_id,
            image_model=payload.image_model, size=payload.size,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WechatMpImageValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/{article_id}/prompts/{prompt_id}/regenerate", response_model=WechatMpImagePromptResponse)
def regenerate_prompt(
    article_id: int,
    prompt_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    article = _get_owned_article(db, current_user, article_id)
    prompt = _get_owned_prompt(db, article, prompt_id)
    try:
        return regenerate_image_prompt(db=db, prompt=prompt, article=article)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
