from __future__ import annotations

import base64
import os
import re
from difflib import SequenceMatcher
from html import escape
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models import WechatMpArticle, WechatMpArticleSection, WechatMpAsset, WechatMpImagePrompt
from backend.app.services.usage_recording_service import record_image_usage
from backend.app.services.illustration_size_service import normalize_illustration_size
from backend.app.services.wechat_mp_cost_service import add_article_cost

PROMPT_REUSE_SIMILARITY_THRESHOLD = 0.92


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


class WechatMpImageValidationError(ValueError):
    pass


def _call_image_model(
    *, prompt: str, model_name: str, size: str, base_url: str = "", api_key: str = "",
) -> dict[str, Any]:
    """Call the configured image provider; tests monkeypatch this narrow seam."""
    base_url = (base_url or os.getenv("WECHAT_MP_IMAGE_BASE_URL", "")).rstrip("/")
    api_key = api_key or os.getenv("WECHAT_MP_IMAGE_API_KEY", "")
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


def _normalize_prompt_for_reuse(prompt: str) -> str:
    return re.sub(r"[\W_]+", "", prompt.lower(), flags=re.UNICODE)


def _prompt_similarity(left: str, right: str) -> float:
    normalized_left = _normalize_prompt_for_reuse(left)
    normalized_right = _normalize_prompt_for_reuse(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def _find_reusable_asset(db: Session, *, user_id: int, prompt: WechatMpImagePrompt) -> tuple[WechatMpAsset, float] | None:
    candidates = db.scalars(
        select(WechatMpAsset)
        .where(
            WechatMpAsset.user_id == user_id,
            WechatMpAsset.role == "inline_illustration",
            WechatMpAsset.status == "generated",
            WechatMpAsset.skill_name == prompt.skill_name,
            WechatMpAsset.public_url != "",
            or_(WechatMpAsset.prompt_id.is_(None), WechatMpAsset.prompt_id != prompt.id),
        )
        .order_by(WechatMpAsset.id.desc())
        .limit(80)
    ).all()
    best: tuple[WechatMpAsset, float] | None = None
    for asset in candidates:
        score = _prompt_similarity(prompt.editable_prompt, asset.prompt)
        if score < PROMPT_REUSE_SIMILARITY_THRESHOLD:
            continue
        if best is None or score > best[1]:
            best = (asset, score)
            if score == 1.0:
                break
    return best


def _update_article_image_state(db: Session, article: WechatMpArticle, prompt: WechatMpImagePrompt) -> None:
    remaining = db.scalars(select(WechatMpImagePrompt.status).where(
        WechatMpImagePrompt.article_id == article.id,
        WechatMpImagePrompt.id != prompt.id,
    )).all()
    article.status = "images_ready" if all(status == "generated" for status in remaining) else "images_partial"


def _reuse_asset_for_prompt(
    db: Session,
    *,
    user_id: int,
    article: WechatMpArticle,
    prompt: WechatMpImagePrompt,
    section: WechatMpArticleSection,
    source_asset: WechatMpAsset,
    similarity: float,
) -> WechatMpAsset:
    from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts

    asset = WechatMpAsset(
        user_id=user_id,
        article_id=article.id,
        prompt_id=prompt.id,
        role="inline_illustration",
        file_path=source_asset.file_path,
        public_url=source_asset.public_url,
        prompt=prompt.editable_prompt,
        skill_name=prompt.skill_name,
        model_name=source_asset.model_name,
        status="generated",
        provider_response={
            "reused_from_asset_id": source_asset.id,
            "reuse_similarity": round(similarity, 4),
        },
    )
    db.add(asset)
    prompt.status = "generated"
    _backfill_article_html(article, prompt, section, asset.public_url)
    invalidate_synced_drafts(db, article, next_status="images_partial")
    _update_article_image_state(db, article, prompt)
    db.commit()
    db.refresh(asset)
    return asset


def generate_asset_for_prompt(
    db: Session,
    user_id: int,
    prompt_id: int,
    image_model: str | None,
    size: str = "16:9",
) -> WechatMpAsset:
    prompt = db.scalar(select(WechatMpImagePrompt).where(
        WechatMpImagePrompt.id == prompt_id,
        WechatMpImagePrompt.user_id == user_id,
    ))
    if prompt is None:
        raise LookupError("WeChat MP prompt not found")
    article = db.get(WechatMpArticle, prompt.article_id)
    section = db.get(WechatMpArticleSection, prompt.section_id)
    if article is None or article.user_id != user_id or section is None or section.article_id != article.id:
        raise LookupError("WeChat MP prompt not found")
    if prompt.skill_name == "none" or article.illustration_skill == "none":
        raise WechatMpImageValidationError("Image generation is disabled when illustration skill is none")
    if prompt.status not in {"prompt_ready", "failed"}:
        raise ValueError("WeChat MP prompt is not ready for image generation")

    from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model
    from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts

    model = resolve_wechat_mp_model(
        db=db, user_id=user_id, model_type="image", requested_model=image_model,
    )
    normalized_size = normalize_illustration_size(model.model_name, size)
    reusable = _find_reusable_asset(db, user_id=user_id, prompt=prompt)
    if reusable is not None:
        source_asset, similarity = reusable
        return _reuse_asset_for_prompt(
            db=db,
            user_id=user_id,
            article=article,
            prompt=prompt,
            section=section,
            source_asset=source_asset,
            similarity=similarity,
        )

    try:
        result = _call_image_model(
            prompt=prompt.editable_prompt, model_name=model.model_name, size=normalized_size,
            base_url=model.base_url, api_key=model.api_key,
        )
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
            model_name=model.model_name,
            status="generated",
            provider_response=result.get("provider_response") if isinstance(result.get("provider_response"), dict) else {},
        )
        db.add(asset)
        prompt.status = "generated"
        _backfill_article_html(article, prompt, section, asset.public_url)
        invalidate_synced_drafts(db, article, next_status="images_partial")
        _update_article_image_state(db, article, prompt)
        db.flush()
        usage = record_image_usage(
            db=db,
            user_id=user_id,
            pipeline_run_id=None,
            step="image_gen",
            model=model.model_name,
            image_count=1,
            platform="wechat_mp",
            resource_type="wechat_mp_article",
            resource_id=article.id,
            commit=False,
        )
        add_article_cost(article, usage.cost_yuan)
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


def generate_cover_asset(
    *, db: Session, user_id: int, article_id: int, image_model: str | None, size: str = "16:9",
) -> WechatMpAsset:
    article = db.scalar(select(WechatMpArticle).where(
        WechatMpArticle.id == article_id,
        WechatMpArticle.user_id == user_id,
    ))
    if article is None:
        raise LookupError("WeChat MP article not found")
    from backend.app.services.wechat_mp_image_prompt_service import build_skill_prompt
    from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model
    from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts

    model = resolve_wechat_mp_model(
        db=db, user_id=user_id, model_type="image", requested_model=image_model,
    )
    normalized_size = normalize_illustration_size(model.model_name, size)
    prompt_text = build_skill_prompt(
        article.illustration_skill, article.title, article.cover_brief or article.title,
    )
    result = _call_image_model(
        prompt=prompt_text, model_name=model.model_name, size=normalized_size,
        base_url=model.base_url, api_key=model.api_key,
    )
    if isinstance(result.get("image_ref"), str):
        file_path, public_url = _save_image_response(result["image_ref"], user_id)
    else:
        file_path = str(result["file_path"])
        public_url = str(result["public_url"])
    asset = WechatMpAsset(
        user_id=user_id,
        article_id=article.id,
        prompt_id=None,
        role="cover",
        file_path=file_path,
        public_url=public_url,
        prompt=prompt_text,
        skill_name=article.illustration_skill,
        model_name=model.model_name,
        status="generated",
        provider_response=result.get("provider_response") if isinstance(result.get("provider_response"), dict) else {},
    )
    db.add(asset)
    invalidate_synced_drafts(db, article, next_status="images_partial")
    db.flush()
    usage = record_image_usage(
        db=db, user_id=user_id, pipeline_run_id=None, step="cover_image_gen",
        model=model.model_name, image_count=1, platform="wechat_mp",
        resource_type="wechat_mp_article", resource_id=article.id, commit=False,
    )
    add_article_cost(article, usage.cost_yuan)
    db.commit()
    db.refresh(asset)
    return asset
