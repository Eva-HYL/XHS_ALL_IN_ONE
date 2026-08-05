from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import (
    User,
    WechatMpArticle,
    WechatMpArticleSection,
    WechatMpAsset,
    WechatMpIllustrationCharacter,
    WechatMpImagePrompt,
    WechatMpPromptIgnoreRule,
)
from backend.app.schemas.wechat_mp import (
    WechatMpArticleCreateRequest,
    WechatMpArticleResponse,
    WechatMpAssetResponse,
    WechatMpImagePromptResponse,
    WechatMpPromptGenerationResponse,
    WechatMpPromptIgnoreRuleResponse,
)
from backend.app.services.wechat_mp_image_service import (
    WechatMpImageValidationError,
    generate_asset_for_prompt,
    generate_cover_asset,
)
from backend.app.services.wechat_mp_image_prompt_service import (
    WechatMpPromptProviderError,
    _restore_prompt_placeholder,
    generate_image_prompts,
    regenerate_image_prompt,
    reset_inline_illustrations,
)
from backend.app.services.wechat_mp_character_service import (
    NONE_SKILL_NAME,
    WechatMpIllustrationSkillError,
    canonicalize_character_prompt,
    parse_character_mention,
    require_character_by_skill,
    resolve_confirmed_character_anchor,
    resolve_character_by_skill,
)
from backend.app.services.wechat_mp_layout_service import apply_wechat_layout_style, get_wechat_layout_styles, normalize_wechat_layout_style, render_wechat_html
from backend.app.services.wechat_mp_writer_service import generate_wechat_article
from backend.app.services.wechat_mp_prompt_ignore_service import ignore_prompt, restore_prompt


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
    character_id: int | None = None
    skill_name: str | None = Field(default=None, min_length=1, max_length=80)


class WechatMpImageGenerateRequest(BaseModel):
    image_model: str | None = Field(default=None, min_length=1, max_length=128)
    size: str = Field(default="16:9", min_length=1, max_length=32)


class WechatMpPromptIgnoreRequest(BaseModel):
    scope: str = Field(default="future_similar", pattern="^(current|future_similar)$")


class WechatMpPromptIgnoreRuleUpdateRequest(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")


class WechatMpLayoutPreviewResponse(BaseModel):
    layout_style: str
    html_body: str


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


def _repair_saved_article_html(db: Session, article: WechatMpArticle) -> WechatMpArticle:
    repaired = apply_wechat_layout_style(article.html_body, "classic")
    if repaired != article.html_body:
        from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts

        article.html_body = repaired
        invalidate_synced_drafts(
            db,
            article,
            next_status=article.status if article.status != "synced_to_wechat" else "layout_ready",
        )
        db.commit()
        db.refresh(article)
    return article


@router.post("", response_model=WechatMpArticleResponse, status_code=status.HTTP_201_CREATED)
def create_article(payload: WechatMpArticleCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return generate_wechat_article(db=db, user_id=current_user.id, request=payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WechatMpIllustrationSkillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("", response_model=list[WechatMpArticleResponse])
def list_articles(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(WechatMpArticle).where(WechatMpArticle.user_id == current_user.id).order_by(WechatMpArticle.id.desc())).all()


@router.get("/layout-styles")
def list_layout_styles(current_user: User = Depends(get_current_user)):
    return get_wechat_layout_styles()


@router.get("/{article_id}", response_model=WechatMpArticleResponse)
def get_article(article_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _repair_saved_article_html(db, _get_owned_article(db, current_user, article_id))


@router.get("/{article_id}/layout-preview", response_model=WechatMpLayoutPreviewResponse)
def preview_article_layout(
    article_id: int,
    layout_style: str = "classic",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    article = _get_owned_article(db, current_user, article_id)
    cover = db.scalar(select(WechatMpAsset).where(
        WechatMpAsset.article_id == article.id,
        WechatMpAsset.user_id == current_user.id,
        WechatMpAsset.role == "cover",
        WechatMpAsset.status == "generated",
    ).order_by(WechatMpAsset.id.desc()))
    try:
        normalized_style = normalize_wechat_layout_style(layout_style)
        html_body = apply_wechat_layout_style(article.html_body, normalized_style, hero_image_url=cover.public_url if cover else None)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"layout_style": normalized_style, "html_body": html_body}


@router.patch("/{article_id}", response_model=WechatMpArticleResponse)
def update_article(article_id: int, payload: WechatMpArticleUpdateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts

    article = _get_owned_article(db, current_user, article_id)
    markdown_changed = payload.markdown_body is not None and payload.markdown_body != article.markdown_body
    html_changed = payload.html_body is not None and payload.html_body != article.html_body
    skill_changed = payload.illustration_skill is not None and payload.illustration_skill != article.illustration_skill
    body_changed = markdown_changed or html_changed
    changed = body_changed or skill_changed

    for field in ("title", "digest"):
        value = getattr(payload, field)
        if value is not None and value != getattr(article, field):
            setattr(article, field, value)
            changed = True

    if markdown_changed:
        article.markdown_body = payload.markdown_body or ""
    if skill_changed:
        try:
            require_character_by_skill(
                db,
                user_id=current_user.id,
                skill_name=payload.illustration_skill or article.illustration_skill,
            )
        except WechatMpIllustrationSkillError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        previous_character = db.scalar(select(WechatMpIllustrationCharacter).where(
            WechatMpIllustrationCharacter.user_id == current_user.id,
            WechatMpIllustrationCharacter.skill_name == article.illustration_skill,
        ))
        article.illustration_skill = payload.illustration_skill or article.illustration_skill
        if article.illustration_skill == NONE_SKILL_NAME:
            article.cover_brief = canonicalize_character_prompt(
                previous_character,
                article.cover_brief,
                include_character=False,
            )
    if body_changed or skill_changed:
        if payload.html_body is not None:
            next_html = payload.html_body
        elif markdown_changed:
            next_html = render_wechat_html(article.markdown_body, image_placeholders=[])
        else:
            next_html = article.html_body
        reset_inline_illustrations(
            db,
            article,
            html_body=next_html,
            preserve_prompt_identity=body_changed,
        )
    if changed:
        invalidate_synced_drafts(db, article, next_status="layout_ready")
    db.commit()
    db.refresh(article)
    return article


@router.post("/{article_id}/prompts", response_model=WechatMpPromptGenerationResponse, status_code=status.HTTP_201_CREATED)
def create_prompts(
    article_id: int,
    payload: WechatMpPromptGenerateRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    article = _get_owned_article(db, current_user, article_id)
    try:
        result = generate_image_prompts(
            db=db,
            user_id=current_user.id,
            article_id=article.id,
            skill_name=payload.skill_name if payload else None,
        )
        return {"items": result.items, "analysis": result.analysis}
    except WechatMpIllustrationSkillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WechatMpPromptProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{article_id}/prompts", response_model=list[WechatMpImagePromptResponse])
def list_prompts(
    article_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    article = _get_owned_article(db, current_user, article_id)
    prompts = db.scalars(
        select(WechatMpImagePrompt)
        .where(WechatMpImagePrompt.article_id == article.id, WechatMpImagePrompt.user_id == current_user.id)
        .order_by(WechatMpImagePrompt.section_id, WechatMpImagePrompt.id)
    ).all()
    repaired = False
    for prompt in prompts:
        stored_text = f"{prompt.prompt}\n{prompt.editable_prompt}"
        if "主角：@" not in stored_text and "胖胖慵懒" not in stored_text:
            continue
        character = db.get(WechatMpIllustrationCharacter, prompt.character_id) if prompt.character_id else None
        if character is None or character.user_id != current_user.id:
            character = resolve_character_by_skill(
                db,
                user_id=current_user.id,
                skill_name=prompt.skill_name,
            )
        if character is None:
            continue
        normalized_prompt = canonicalize_character_prompt(character, prompt.prompt, include_character=True)
        normalized_editable = canonicalize_character_prompt(character, prompt.editable_prompt, include_character=True)
        section = db.get(WechatMpArticleSection, prompt.section_id)
        fallback_scene = (section.summary or section.source_excerpt).strip() if section is not None else ""
        if fallback_scene:
            if not parse_character_mention(normalized_prompt)[1].removeprefix("具体画面：").strip():
                normalized_prompt = canonicalize_character_prompt(character, fallback_scene, include_character=True)
            if not parse_character_mention(normalized_editable)[1].removeprefix("具体画面：").strip():
                normalized_editable = canonicalize_character_prompt(character, fallback_scene, include_character=True)
        if normalized_prompt != prompt.prompt or normalized_editable != prompt.editable_prompt:
            prompt.prompt = normalized_prompt
            prompt.editable_prompt = normalized_editable
            repaired = True
    if repaired:
        db.commit()
        for prompt in prompts:
            db.refresh(prompt)
    return prompts


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
    try:
        parse_character_mention(payload.editable_prompt)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    identity_changed = payload.character_id is not None or payload.skill_name is not None
    selected_skill = payload.skill_name or prompt.skill_name
    try:
        if identity_changed:
            if selected_skill == NONE_SKILL_NAME:
                if payload.character_id is not None:
                    raise ValueError("none cannot reference a character")
                character = None
            else:
                character, _ = resolve_confirmed_character_anchor(
                    db,
                    user_id=current_user.id,
                    character_id=payload.character_id,
                    skill_name=None if payload.character_id is not None else selected_skill,
                )
                if character.archived_at is not None:
                    raise ValueError("Selected character is not available")
                if payload.skill_name is not None and character.skill_name != payload.skill_name:
                    raise ValueError("Character skill does not match character_id")
                selected_skill = character.skill_name
        else:
            character = resolve_character_by_skill(
                db,
                user_id=current_user.id,
                skill_name=selected_skill,
            )
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    prompt.editable_prompt = canonicalize_character_prompt(
        character,
        payload.editable_prompt,
        include_character=character is not None,
    )
    prompt.character_id = character.id if character is not None else None
    prompt.skill_name = selected_skill
    prompt.version += 1
    prompt.status = "skipped" if prompt.skill_name == NONE_SKILL_NAME else "prompt_ready"
    if prompt.skill_name != NONE_SKILL_NAME:
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
    except WechatMpIllustrationSkillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/{article_id}/prompts/{prompt_id}/ignore", response_model=WechatMpImagePromptResponse)
def ignore_article_prompt(
    article_id: int,
    prompt_id: int,
    payload: WechatMpPromptIgnoreRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_article(db, current_user, article_id)
    try:
        return ignore_prompt(
            db,
            user_id=current_user.id,
            article_id=article_id,
            prompt_id=prompt_id,
            future_similar=payload.scope == "future_similar",
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{article_id}/prompts/{prompt_id}/restore", response_model=WechatMpImagePromptResponse)
def restore_article_prompt(
    article_id: int,
    prompt_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_article(db, current_user, article_id)
    try:
        return restore_prompt(db, user_id=current_user.id, article_id=article_id, prompt_id=prompt_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@image_router.get("/prompt-ignore-rules", response_model=list[WechatMpPromptIgnoreRuleResponse])
def list_prompt_ignore_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.scalars(select(WechatMpPromptIgnoreRule).where(
        WechatMpPromptIgnoreRule.user_id == current_user.id,
    ).order_by(WechatMpPromptIgnoreRule.id.desc())).all()


@image_router.patch("/prompt-ignore-rules/{rule_id}", response_model=WechatMpPromptIgnoreRuleResponse)
def update_prompt_ignore_rule(
    rule_id: int,
    payload: WechatMpPromptIgnoreRuleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rule = db.scalar(select(WechatMpPromptIgnoreRule).where(
        WechatMpPromptIgnoreRule.id == rule_id,
        WechatMpPromptIgnoreRule.user_id == current_user.id,
    ))
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP ignore rule not found")
    rule.status = payload.status
    db.commit()
    db.refresh(rule)
    return rule


@image_router.delete("/prompt-ignore-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt_ignore_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rule = db.scalar(select(WechatMpPromptIgnoreRule).where(
        WechatMpPromptIgnoreRule.id == rule_id,
        WechatMpPromptIgnoreRule.user_id == current_user.id,
    ))
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP ignore rule not found")
    db.delete(rule)
    db.commit()
