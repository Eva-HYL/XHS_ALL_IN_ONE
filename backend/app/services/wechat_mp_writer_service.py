from __future__ import annotations

import json
import os
from typing import Any

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import WechatMpArticle, WechatMpArticleMaterial, WechatMpMaterial
from backend.app.schemas.wechat_mp import WechatMpArticleCreateRequest
from backend.app.services.usage_recording_service import record_text_usage
from backend.app.services.wechat_mp_character_service import (
    XIAOMAO_SKILL_NAME,
    canonicalize_character_prompt,
    require_character_by_skill,
)
from backend.app.services.wechat_mp_layout_service import render_wechat_html


_WRITER_PROMPT = """你是微信公众号文章编辑。根据输入写一篇中文文章，并只返回 JSON。
JSON 必须包含 title、markdown_body、digest、cover_brief。正文使用 Markdown。
title 必须与输入的 title_hint 完全一致，不得改写。
cover_brief 必须描述可直接绘制的封面场景，明确主题物、结构关系和主角动作，不能只复述文章标题。
封面应让主题结构是主体，角色只作辅助；不要输出画幅、尺寸、水印、签名或让模型渲染标题的指令。"""

_WRITING_BRIEF_PROMPT = """你是微信公众号选题编辑。根据用户想法和资料整理一份精简写作简报，并只返回 JSON。
JSON 必须包含 title、topic、target_reader、tone，四个字段都必须是中文字符串。
title 是可直接使用的文章标题；topic 概括文章主题、核心观点和写作范围；target_reader 描述目标读者；tone 描述语气和表达风格。
只依据输入资料提炼，不虚构资料中没有的事实，不输出正文、大纲、Markdown 或额外字段。"""


class WechatMpWritingBriefSourceError(ValueError):
    pass


def _selected_material_ids(material_ids: list[int]) -> list[int]:
    seen = set()
    selected = []
    for material_id in material_ids:
        if material_id in seen:
            continue
        seen.add(material_id)
        selected.append(material_id)
    return selected


def _load_selected_materials(db: Session, user_id: int, material_ids: list[int]) -> list[WechatMpMaterial]:
    selected_ids = _selected_material_ids(material_ids)
    if not selected_ids:
        return []
    materials = db.scalars(select(WechatMpMaterial).where(
        WechatMpMaterial.user_id == user_id,
        WechatMpMaterial.status == "active",
        WechatMpMaterial.id.in_(selected_ids),
    )).all()
    material_by_id = {material.id: material for material in materials}
    missing_ids = [material_id for material_id in selected_ids if material_id not in material_by_id]
    if missing_ids:
        raise LookupError("WeChat MP selected materials are not available: " + ", ".join(str(item) for item in missing_ids))
    return [material_by_id[material_id] for material_id in selected_ids]


def _compose_source_material(manual_material: str, selected_materials: list[WechatMpMaterial]) -> str:
    parts = []
    if manual_material.strip():
        parts.append("【手动输入素材】\n" + manual_material.strip())
    for material in selected_materials:
        lines = [f"【素材库：{material.title}】"]
        if material.source_url:
            lines.append(f"来源：{material.source_url}")
        if material.content:
            lines.append(material.content)
        if material.notes:
            lines.append(f"备注：{material.notes}")
        parts.append("\n".join(lines))
    return "\n\n---\n\n".join(parts)


def _call_writer_model(
    *, title_hint: str, topic: str, source_material: str, target_reader: str, tone: str,
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
                        "title_hint": title_hint,
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


def _call_writing_brief_model(
    *, idea: str, source_material: str, model_name: str, base_url: str = "", api_key: str = "",
) -> dict[str, Any]:
    """Call the text model through a narrow seam that brief tests can replace."""
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
                    {"role": "system", "content": _WRITING_BRIEF_PROMPT},
                    {"role": "user", "content": json.dumps({
                        "idea": idea,
                        "source_material": source_material,
                    }, ensure_ascii=False)},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        result = json.loads(payload["choices"][0]["message"]["content"])
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("WeChat MP writing brief model returned malformed JSON") from exc
    required = ("title", "topic", "target_reader", "tone")
    if not isinstance(result, dict) or not all(isinstance(result.get(key), str) for key in required):
        raise ValueError("WeChat MP writing brief response is missing fields")
    if not result["title"].strip() or not result["topic"].strip():
        raise ValueError("WeChat MP writing brief response is empty")
    usage = payload.get("usage") or {}
    return {
        **result,
        "input_tokens": int(usage.get("prompt_tokens", 0)),
        "output_tokens": int(usage.get("completion_tokens", 0)),
        "model_name": model_name,
    }


def prepare_wechat_writing_brief(
    *, db: Session, user_id: int, material_ids: list[int], idea: str,
) -> dict[str, Any]:
    from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model

    selected_materials = _load_selected_materials(db, user_id, material_ids)
    source_material = _compose_source_material("", selected_materials)
    normalized_idea = idea.strip()
    if not normalized_idea and not source_material.strip():
        raise WechatMpWritingBriefSourceError("请先选择素材或输入一句话想法")
    model = resolve_wechat_mp_model(db=db, user_id=user_id, model_type="text")
    result = _call_writing_brief_model(
        idea=normalized_idea,
        source_material=source_material,
        model_name=model.model_name,
        base_url=model.base_url,
        api_key=model.api_key,
    )
    usage = record_text_usage(
        db=db,
        user_id=user_id,
        pipeline_run_id=None,
        step="prepare_writing_brief",
        model=result["model_name"],
        input_tokens=int(result["input_tokens"]),
        output_tokens=int(result["output_tokens"]),
        platform="wechat_mp",
        resource_type="wechat_mp_writing_brief",
        resource_id=None,
    )
    return {
        "title": result["title"].strip()[:255],
        "topic": result["topic"].strip(),
        "target_reader": result["target_reader"].strip(),
        "tone": result["tone"].strip(),
        "cost_estimate": {
            "currency": "CNY",
            "total_yuan": str(usage.cost_yuan),
            "calls": 1,
        },
    }


def generate_wechat_article(*, db: Session, user_id: int, request: WechatMpArticleCreateRequest) -> WechatMpArticle:
    from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model

    illustration_skill = request.illustration_skill or XIAOMAO_SKILL_NAME
    character = require_character_by_skill(db, user_id=user_id, skill_name=illustration_skill)
    model = resolve_wechat_mp_model(db=db, user_id=user_id, model_type="text")
    selected_materials = _load_selected_materials(db, user_id, request.material_ids)
    result = _call_writer_model(
        title_hint=request.title.strip(),
        topic=request.topic,
        source_material=_compose_source_material(request.source_material, selected_materials),
        target_reader=request.target_reader,
        tone=request.tone,
        model_name=model.model_name,
        base_url=model.base_url,
        api_key=model.api_key,
    )
    result["title"] = request.title.strip()
    cover_brief = canonicalize_character_prompt(
        character,
        result["cover_brief"],
        include_character=character is not None,
    )
    try:
        article = WechatMpArticle(
            user_id=user_id,
            title=result["title"],
            markdown_body=result["markdown_body"],
            html_body=render_wechat_html(result["markdown_body"], image_placeholders=[]),
            digest=result["digest"],
            cover_brief=cover_brief,
            status="layout_ready",
            illustration_skill=illustration_skill,
        )
        db.add(article)
        db.flush()
        for material in selected_materials:
            db.add(WechatMpArticleMaterial(
                user_id=user_id,
                article_id=article.id,
                material_id=material.id,
            ))
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
