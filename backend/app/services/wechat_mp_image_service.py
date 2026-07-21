from __future__ import annotations

import base64
import os
from html import escape
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models import WechatMpArticle, WechatMpArticleSection, WechatMpAsset, WechatMpImagePrompt
from backend.app.services.usage_recording_service import record_image_usage


def _media_dir() -> Path:
    return Path(get_settings().storage_dir) / "media"


def _save_image_response(image_ref: str, user_id: int) -> tuple[str, str]:
    """Persist provider output in the shared media store under a WeChat-specific name."""
    media_dir = _media_dir()
    media_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"wechat-mp-u{user_id}-{uuid4().hex}.png"
    path = media_dir / file_name
    if image_ref.startswith(("http://", "https://")):
        response = requests.get(image_ref, timeout=30)
        response.raise_for_status()
        content = response.content
    else:
        content = base64.b64decode(image_ref)
    if not content:
        raise ValueError("WeChat MP image model returned an empty image")
    path.write_bytes(content)
    return str(path), f"/api/files/media/{file_name}"


def _call_image_model(*, prompt: str, model_name: str, size: str) -> dict[str, Any]:
    """Call the configured image provider; tests monkeypatch this narrow seam."""
    base_url = os.getenv("WECHAT_MP_IMAGE_BASE_URL", "").rstrip("/")
    api_key = os.getenv("WECHAT_MP_IMAGE_API_KEY", "")
    if not base_url or not api_key:
        raise ValueError("WeChat MP image model is not configured")
    try:
        response = requests.post(
            f"{base_url}/images/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model_name, "prompt": prompt, "size": size, "response_format": "url"},
            timeout=180,
        )
        response.raise_for_status()
        provider_response = response.json()
        item = provider_response["data"][0]
        image_ref = item.get("url") or item.get("b64_json")
        if not isinstance(image_ref, str) or not image_ref:
            raise ValueError("image response missing url or b64_json")
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("WeChat MP image model returned malformed output") from exc
    return {"image_ref": image_ref, "provider_response": provider_response}


def _backfill_article_html(article: WechatMpArticle, prompt: WechatMpImagePrompt, section: WechatMpArticleSection, public_url: str) -> None:
    marker = f"{{{{image:prompt-{prompt.id}}}}}"
    image_html = f'<img src="{escape(public_url, quote=True)}" alt="{escape(section.summary, quote=True)}" />'
    article.html_body = article.html_body.replace(marker, image_html)


def generate_asset_for_prompt(
    db: Session,
    user_id: int,
    prompt_id: int,
    image_model: str,
    size: str = "16:9",
) -> WechatMpAsset:
    prompt = db.scalar(select(WechatMpImagePrompt).where(
        WechatMpImagePrompt.id == prompt_id,
        WechatMpImagePrompt.user_id == user_id,
    ))
    if prompt is None:
        raise LookupError("WeChat MP prompt not found")
    if prompt.status != "prompt_ready":
        raise ValueError("WeChat MP prompt is not ready for image generation")
    article = db.get(WechatMpArticle, prompt.article_id)
    section = db.get(WechatMpArticleSection, prompt.section_id)
    if article is None or article.user_id != user_id or section is None or section.article_id != article.id:
        raise LookupError("WeChat MP prompt not found")

    try:
        result = _call_image_model(prompt=prompt.editable_prompt, model_name=image_model, size=size)
        if isinstance(result.get("image_ref"), str):
            file_path, public_url = _save_image_response(result["image_ref"], user_id)
        else:
            file_path = str(result["file_path"])
            public_url = str(result["public_url"])
        asset = WechatMpAsset(
            user_id=user_id,
            article_id=article.id,
            prompt_id=prompt.id,
            role="inline_illustration",
            file_path=file_path,
            public_url=public_url,
            prompt=prompt.editable_prompt,
            skill_name=prompt.skill_name,
            model_name=image_model,
            status="generated",
            provider_response=result.get("provider_response") if isinstance(result.get("provider_response"), dict) else {},
        )
        db.add(asset)
        prompt.status = "generated"
        _backfill_article_html(article, prompt, section, asset.public_url)
        remaining = db.scalars(select(WechatMpImagePrompt.status).where(
            WechatMpImagePrompt.article_id == article.id,
            WechatMpImagePrompt.id != prompt.id,
        )).all()
        article.status = "images_ready" if all(status == "generated" for status in remaining) else "images_partial"
        db.flush()
        record_image_usage(
            db=db,
            user_id=user_id,
            pipeline_run_id=None,
            step="image_gen",
            model=image_model,
            image_count=1,
            platform="wechat_mp",
            resource_type="wechat_mp_article",
            resource_id=article.id,
            commit=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        prompt = db.get(WechatMpImagePrompt, prompt_id)
        if prompt is not None:
            prompt.status = "failed"
            db.commit()
        raise
    db.refresh(asset)
    return asset
