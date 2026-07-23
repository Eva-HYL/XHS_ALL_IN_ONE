from __future__ import annotations

import os
import re
from html import escape
from typing import Any

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import WechatMpArticle, WechatMpArticleSection, WechatMpAsset, WechatMpImagePrompt
from backend.app.services.usage_recording_service import record_text_usage
from backend.app.services.wechat_mp_character_service import XIAOMAO_SKILL_NAME, resolve_character_prompt
from backend.app.services.wechat_mp_cost_service import add_article_cost
from backend.app.services.wechat_mp_layout_service import render_wechat_html
from backend.app.services.wechat_mp_shotlist_service import generate_article_shotlist


_PROMPT_SYSTEM = "You write concise image prompts for Chinese WeChat article illustrations. Return only the image prompt."
def build_skill_prompt(
    skill_name: str,
    article_title: str,
    section_summary: str,
    db: Session | None = None,
    user_id: int | None = None,
) -> str:
    character_prompt = resolve_character_prompt(db, user_id, skill_name)
    diagram_contract = ""
    if "图解类型：" in section_summary:
        diagram_contract = (
            "\n图解硬约束：必须逐字保留图解节点、分类名称和顺序；"
            "优先画清晰的信息图、流程图、结构图或对比卡片；"
            "不要把流程改成泛化插画，不要省略箭头、节点或关键文字；"
            "主角形象只能作为角落辅助讲解，不得遮挡或替代图解主体。"
        )
    if character_prompt:
        return f"{character_prompt}{diagram_contract}\n文章：{article_title}\n场景：{section_summary}"
    return f"16:9 微信公众号正文插画。{diagram_contract}\n文章：{article_title}\n场景：{section_summary}"


def _insert_prompt_placeholder(article: WechatMpArticle, section: WechatMpArticleSection, prompt: WechatMpImagePrompt) -> None:
    """Add the stable image marker near its source section without duplicating it."""
    marker = f"{{{{image:prompt-{prompt.id}}}}}"
    if marker in article.html_body:
        return

    section_html = render_wechat_html(section.source_excerpt, image_placeholders=[])
    if section_html and section_html in article.html_body:
        article.html_body = article.html_body.replace(section_html, f"{section_html}\n{marker}", 1)
    else:
        article.html_body = f"{article.html_body}\n{marker}" if article.html_body else marker


def _restore_prompt_placeholder(db: Session, article: WechatMpArticle, section: WechatMpArticleSection, prompt: WechatMpImagePrompt) -> None:
    """Replace the most recently embedded image so a regenerated prompt can backfill it."""
    marker = f"{{{{image:prompt-{prompt.id}}}}}"
    if marker in article.html_body:
        return
    asset = db.scalar(
        select(WechatMpAsset)
        .where(WechatMpAsset.article_id == article.id, WechatMpAsset.prompt_id == prompt.id)
        .order_by(WechatMpAsset.id.desc())
    )
    if asset is None:
        _insert_prompt_placeholder(article, section, prompt)
        return
    image_pattern = re.compile(r'<img src="' + re.escape(escape(asset.public_url, quote=True)) + r'" alt="[^"]*" />')
    if image_pattern.search(article.html_body):
        article.html_body = image_pattern.sub(marker, article.html_body, count=1)
    else:
        _insert_prompt_placeholder(article, section, prompt)


def reset_inline_illustrations(
    db: Session,
    article: WechatMpArticle,
    *,
    html_body: str | None = None,
) -> str:
    """Remove obsolete inline planning state while retaining generated assets as history."""
    prompts = db.scalars(
        select(WechatMpImagePrompt).where(WechatMpImagePrompt.article_id == article.id)
    ).all()
    sections = db.scalars(
        select(WechatMpArticleSection).where(WechatMpArticleSection.article_id == article.id)
    ).all()
    inline_assets = db.scalars(
        select(WechatMpAsset).where(
            WechatMpAsset.article_id == article.id,
            WechatMpAsset.role == "inline_illustration",
        )
    ).all()

    cleaned_html = article.html_body if html_body is None else html_body
    for asset in inline_assets:
        image_pattern = re.compile(
            r'<img\b[^>]*\bsrc=["\']'
            + re.escape(escape(asset.public_url, quote=True))
            + r'["\'][^>]*>'
        )
        cleaned_html = image_pattern.sub("", cleaned_html)
        asset.prompt_id = None
    cleaned_html = re.sub(r"\{\{image:prompt-\d+\}\}", "", cleaned_html)

    # Detach historical assets before deleting prompt rows to satisfy foreign keys.
    db.flush()
    for prompt in prompts:
        db.delete(prompt)
    db.flush()
    for section in sections:
        db.delete(section)
    article.html_body = cleaned_html
    return cleaned_html


def _parse_token_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("token count must be an integer")
    if value < 0:
        raise ValueError("token count must not be negative")
    return value


def _call_prompt_model(
    *, article_title: str, section_summary: str, skill_name: str, model_name: str,
    base_url: str = "", api_key: str = "", db: Session | None = None, user_id: int | None = None,
) -> dict[str, Any]:
    """Call the configured prompt model; kept narrow for monkeypatch-based tests."""
    base_url = (base_url or os.getenv("WECHAT_MP_PROMPT_BASE_URL", "")).rstrip("/")
    api_key = api_key or os.getenv("WECHAT_MP_PROMPT_API_KEY", "")
    if not base_url or not api_key:
        raise ValueError("WeChat MP prompt model is not configured")
    prompt_contract = build_skill_prompt(skill_name, article_title, section_summary, db=db, user_id=user_id)
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": f"{_PROMPT_SYSTEM}\n{prompt_contract}"},
                    {"role": "user", "content": prompt_contract},
                ],
            },
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("prompt content must be a string")
        prompt = content.strip()
        usage = payload.get("usage") or {}
        if not isinstance(usage, dict):
            raise ValueError("usage must be an object")
        input_tokens = _parse_token_count(usage.get("prompt_tokens", 0))
        output_tokens = _parse_token_count(usage.get("completion_tokens", 0))
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("WeChat MP prompt model returned malformed output") from exc
    if not prompt:
        raise ValueError("WeChat MP prompt model returned an empty prompt")
    return {
        "prompt": f"{prompt_contract}\n具体画面：{prompt}",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model_name": model_name,
    }


def generate_image_prompts(*, db: Session, user_id: int, article_id: int, skill_name: str | None) -> list[WechatMpImagePrompt]:
    from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model

    article = db.scalar(select(WechatMpArticle).where(WechatMpArticle.id == article_id, WechatMpArticle.user_id == user_id))
    if article is None:
        raise LookupError("WeChat MP article not found")
    selected_skill = skill_name or article.illustration_skill or XIAOMAO_SKILL_NAME
    if selected_skill == "none" and article.illustration_skill != "none":
        has_inline_state = bool(db.scalar(
            select(WechatMpImagePrompt.id).where(WechatMpImagePrompt.article_id == article.id).limit(1)
        )) or "{{image:prompt-" in article.html_body
        if has_inline_state:
            reset_inline_illustrations(db, article)
        article.illustration_skill = "none"
    model = resolve_wechat_mp_model(db=db, user_id=user_id, model_type="text")
    try:
        sections = generate_article_shotlist(db=db, user_id=user_id, article_id=article_id, text_model=model.model_name)
        prompts = []
        revision_invalidated = False
        for section in sections:
            prompt = db.scalar(
                select(WechatMpImagePrompt)
                .where(WechatMpImagePrompt.article_id == article.id, WechatMpImagePrompt.section_id == section.id)
                .order_by(WechatMpImagePrompt.id.desc())
            )
            result = _call_prompt_model(
                article_title=article.title,
                section_summary=section.summary,
                skill_name=selected_skill,
                model_name=model.model_name,
                base_url=model.base_url,
                api_key=model.api_key,
                db=db,
                user_id=user_id,
            )
            prompt_status = "skipped" if selected_skill == "none" else "prompt_ready"
            if prompt is None:
                prompt = WechatMpImagePrompt(
                    user_id=user_id,
                    article_id=article.id,
                    section_id=section.id,
                    skill_name=selected_skill,
                    prompt=result["prompt"],
                    editable_prompt=result["prompt"],
                    version=1,
                    status=prompt_status,
                )
                db.add(prompt)
                db.flush()
            else:
                if selected_skill != "none":
                    _restore_prompt_placeholder(db, article, section, prompt)
                prompt.skill_name = selected_skill
                prompt.prompt = result["prompt"]
                prompt.editable_prompt = result["prompt"]
                prompt.version += 1
                prompt.status = prompt_status
            if selected_skill != "none":
                _insert_prompt_placeholder(article, section, prompt)
            usage = record_text_usage(
                db=db,
                user_id=user_id,
                pipeline_run_id=None,
                step="generate_image_prompt",
                model=result["model_name"],
                input_tokens=int(result["input_tokens"]),
                output_tokens=int(result["output_tokens"]),
                platform="wechat_mp",
                resource_type="wechat_mp_article",
                resource_id=article.id,
                commit=False,
            )
            prompt.cost_estimate = {
                "currency": "CNY", "total_yuan": str(usage.cost_yuan), "calls": 1,
            }
            add_article_cost(article, usage.cost_yuan)
            prompts.append(prompt)
            article.illustration_skill = selected_skill
            if not revision_invalidated:
                from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts
                invalidate_synced_drafts(db, article, next_status="prompts_ready")
                revision_invalidated = True
            else:
                article.status = "prompts_ready"
            # Each completed provider call is durable even if a later section fails.
            db.commit()
    except Exception:
        db.rollback()
        raise
    for prompt in prompts:
        db.refresh(prompt)
    return prompts


def regenerate_image_prompt(*, db: Session, prompt: WechatMpImagePrompt, article: WechatMpArticle) -> WechatMpImagePrompt:
    from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model

    section = db.get(WechatMpArticleSection, prompt.section_id)
    if section is None or section.article_id != article.id:
        raise LookupError("WeChat MP prompt not found")
    model = resolve_wechat_mp_model(db=db, user_id=article.user_id, model_type="text")
    result = _call_prompt_model(
        article_title=article.title,
        section_summary=section.summary,
        skill_name=prompt.skill_name,
        model_name=model.model_name,
        base_url=model.base_url,
        api_key=model.api_key,
    )
    prompt.prompt = result["prompt"]
    prompt.editable_prompt = result["prompt"]
    prompt.version += 1
    prompt.status = "skipped" if prompt.skill_name == "none" else "prompt_ready"
    if prompt.skill_name != "none":
        _restore_prompt_placeholder(db, article, section, prompt)
    usage = record_text_usage(
        db=db,
        user_id=article.user_id,
        pipeline_run_id=None,
        step="generate_image_prompt",
        model=result["model_name"],
        input_tokens=int(result["input_tokens"]),
        output_tokens=int(result["output_tokens"]),
        platform="wechat_mp",
        resource_type="wechat_mp_article",
        resource_id=article.id,
        commit=False,
    )
    prompt.cost_estimate = {
        "currency": "CNY", "total_yuan": str(usage.cost_yuan), "calls": 1,
    }
    add_article_cost(article, usage.cost_yuan)
    from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts
    invalidate_synced_drafts(db, article, next_status="prompts_ready")
    db.commit()
    db.refresh(prompt)
    return prompt
