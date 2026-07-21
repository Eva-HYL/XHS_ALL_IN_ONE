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
from backend.app.services.wechat_mp_layout_service import render_wechat_html
from backend.app.services.wechat_mp_shotlist_service import generate_article_shotlist


_PROMPT_SYSTEM = "You write concise image prompts for Chinese WeChat article illustrations. Return only the image prompt."


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


def _parse_token_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("token count must be an integer")
    if value < 0:
        raise ValueError("token count must not be negative")
    return value


def _call_prompt_model(*, article_title: str, section_summary: str, skill_name: str, model_name: str) -> dict[str, Any]:
    """Call the configured prompt model; kept narrow for monkeypatch-based tests."""
    base_url = os.getenv("WECHAT_MP_PROMPT_BASE_URL", "").rstrip("/")
    api_key = os.getenv("WECHAT_MP_PROMPT_API_KEY", "")
    if not base_url or not api_key:
        raise ValueError("WeChat MP prompt model is not configured")
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": _PROMPT_SYSTEM},
                    {"role": "user", "content": f"Title: {article_title}\nSection: {section_summary}\nSkill: {skill_name}"},
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
        "prompt": prompt,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model_name": model_name,
    }


def generate_image_prompts(*, db: Session, user_id: int, article_id: int, skill_name: str | None, text_model: str) -> list[WechatMpImagePrompt]:
    article = db.scalar(select(WechatMpArticle).where(WechatMpArticle.id == article_id, WechatMpArticle.user_id == user_id))
    if article is None:
        raise LookupError("WeChat MP article not found")
    selected_skill = skill_name or article.illustration_skill or "xiaomao-illustrations"
    try:
        sections = generate_article_shotlist(db=db, user_id=user_id, article_id=article_id, text_model=text_model)
        prompts = []
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
                model_name=text_model,
            )
            if prompt is None:
                prompt = WechatMpImagePrompt(
                    user_id=user_id,
                    article_id=article.id,
                    section_id=section.id,
                    skill_name=selected_skill,
                    prompt=result["prompt"],
                    editable_prompt=result["prompt"],
                    version=1,
                    status="prompt_ready",
                )
                db.add(prompt)
                db.flush()
            else:
                _restore_prompt_placeholder(db, article, section, prompt)
                prompt.skill_name = selected_skill
                prompt.prompt = result["prompt"]
                prompt.editable_prompt = result["prompt"]
                prompt.version += 1
                prompt.status = "prompt_ready"
            _insert_prompt_placeholder(article, section, prompt)
            record_text_usage(
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
            prompts.append(prompt)
        article.illustration_skill = selected_skill
        article.status = "prompts_ready"
        db.commit()
    except Exception:
        db.rollback()
        raise
    for prompt in prompts:
        db.refresh(prompt)
    return prompts


def regenerate_image_prompt(*, db: Session, prompt: WechatMpImagePrompt, article: WechatMpArticle, text_model: str) -> WechatMpImagePrompt:
    section = db.get(WechatMpArticleSection, prompt.section_id)
    if section is None or section.article_id != article.id:
        raise LookupError("WeChat MP prompt not found")
    result = _call_prompt_model(
        article_title=article.title,
        section_summary=section.summary,
        skill_name=prompt.skill_name,
        model_name=text_model,
    )
    prompt.prompt = result["prompt"]
    prompt.editable_prompt = result["prompt"]
    prompt.version += 1
    prompt.status = "prompt_ready"
    _restore_prompt_placeholder(db, article, section, prompt)
    record_text_usage(
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
    article.status = "prompts_ready"
    db.commit()
    db.refresh(prompt)
    return prompt
