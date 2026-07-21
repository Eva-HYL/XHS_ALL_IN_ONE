from __future__ import annotations

import json
import os
from typing import Any

import requests
from sqlalchemy.orm import Session

from backend.app.models import WechatMpArticle
from backend.app.schemas.wechat_mp import WechatMpArticleCreateRequest
from backend.app.services.usage_recording_service import record_text_usage
from backend.app.services.wechat_mp_layout_service import render_wechat_html


_WRITER_PROMPT = """你是微信公众号文章编辑。根据输入写一篇中文文章，并只返回 JSON。
JSON 必须包含 title、markdown_body、digest、cover_brief。正文使用 Markdown。"""


def _call_writer_model(
    *, topic: str, source_material: str, target_reader: str, tone: str,
    model_name: str, base_url: str = "", api_key: str = "",
) -> dict[str, Any]:
    """Call the configured OpenAI-compatible writer endpoint.

    This intentionally narrow function is the monkeypatch seam for article generation.
    """
    base_url = (base_url or os.getenv("WECHAT_MP_WRITER_BASE_URL", "")).rstrip("/")
    api_key = api_key or os.getenv("WECHAT_MP_WRITER_API_KEY", "")
    if not base_url or not api_key:
        raise ValueError("WeChat MP writer model is not configured")
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": _WRITER_PROMPT},
                    {"role": "user", "content": json.dumps({
                        "topic": topic,
                        "source_material": source_material,
                        "target_reader": target_reader,
                        "tone": tone,
                    }, ensure_ascii=False)},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        result = json.loads(payload["choices"][0]["message"]["content"])
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("WeChat MP writer returned malformed JSON") from exc
    if not isinstance(result, dict) or not all(isinstance(result.get(key), str) for key in ("title", "markdown_body", "digest", "cover_brief")):
        raise ValueError("WeChat MP writer response is missing article fields")
    usage = payload.get("usage") or {}
    return {
        **result,
        "input_tokens": int(usage.get("prompt_tokens", 0)),
        "output_tokens": int(usage.get("completion_tokens", 0)),
        "model_name": model_name,
    }


def generate_wechat_article(*, db: Session, user_id: int, request: WechatMpArticleCreateRequest) -> WechatMpArticle:
    from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model

    model = resolve_wechat_mp_model(db=db, user_id=user_id, model_type="text")
    result = _call_writer_model(
        topic=request.topic,
        source_material=request.source_material,
        target_reader=request.target_reader,
        tone=request.tone,
        model_name=model.model_name,
        base_url=model.base_url,
        api_key=model.api_key,
    )
    try:
        article = WechatMpArticle(
            user_id=user_id,
            title=result["title"],
            markdown_body=result["markdown_body"],
            html_body=render_wechat_html(result["markdown_body"], image_placeholders=[]),
            digest=result["digest"],
            cover_brief=result["cover_brief"],
            status="layout_ready",
            illustration_skill=request.illustration_skill or "xiaomao-illustrations",
        )
        db.add(article)
        db.flush()
        usage = record_text_usage(
            db=db,
            user_id=user_id,
            pipeline_run_id=None,
            step="write_article",
            model=result["model_name"],
            input_tokens=int(result["input_tokens"]),
            output_tokens=int(result["output_tokens"]),
            platform="wechat_mp",
            resource_type="wechat_mp_article",
            resource_id=article.id,
            commit=False,
        )
        article.cost_estimate = {
            "currency": "CNY",
            "total_yuan": str(usage.cost_yuan),
            "calls": 1,
        }
        db.commit()
        db.refresh(article)
        return article
    except (KeyError, TypeError, ValueError) as exc:
        db.rollback()
        raise ValueError("WeChat MP writer response is invalid") from exc
