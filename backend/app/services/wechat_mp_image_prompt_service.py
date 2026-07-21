from __future__ import annotations

import os
from typing import Any

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import WechatMpArticle, WechatMpArticleSection, WechatMpImagePrompt
from backend.app.services.usage_recording_service import record_text_usage
from backend.app.services.wechat_mp_shotlist_service import generate_article_shotlist


_PROMPT_SYSTEM = "You write concise image prompts for Chinese WeChat article illustrations. Return only the image prompt."


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
            result = _call_prompt_model(
                article_title=article.title,
                section_summary=section.summary,
                skill_name=selected_skill,
                model_name=text_model,
            )
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
    )
    db.refresh(prompt)
    return prompt
