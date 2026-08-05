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
from backend.app.services.wechat_mp_layout_service import clean_markdown_plain_text

PROMPT_REUSE_SIMILARITY_THRESHOLD = 0.92
_NUMBERED_SCENE_ROW_RE = re.compile(r"^\s*(\d+)\s*(?:[|｜、.．:：])\s*(.+?)\s*$")
_SCENE_FLOW_SPLIT_RE = re.compile(r"\s*(?:→|->|⇒|=>|＞)\s*")


def _structured_scene_contract(scene_prompt: str) -> str:
    """Repeat ordered and tabular structures as explicit final-generation constraints."""
    scene = scene_prompt.strip().removeprefix("具体画面：").strip()
    numbered_rows: list[tuple[str, str]] = []
    for line in scene.splitlines():
        match = _NUMBERED_SCENE_ROW_RE.match(line)
        if match is None:
            continue
        numbered_rows.append((match.group(1), re.sub(r"\s*[|｜]\s*", "｜", match.group(2)).strip()))
    if len(numbered_rows) >= 2:
        numbers = " -> ".join(number for number, _ in numbered_rows)
        rows = "\n".join(f"{number}｜{content}" for number, content in numbered_rows)
        return (
            "\n顺序图硬约束：固定顺序："
            f"{numbers}。按编号从左到右排列，空间不足时从上到下；每个编号对应一个独立节点，"
            "不得交换、合并、省略或新增节点，不得让连线跨越错误节点；主角最多出现一次。\n"
            f"有序节点原文：\n{rows}"
        )

    table_rows: list[list[str]] = []
    for line in scene.splitlines():
        cells = [cell.strip().lstrip("#").strip() for cell in re.split(r"[|｜]", line.strip().strip("|｜"))]
        if len(cells) < 2 or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        table_rows.append(cells)
    if len(table_rows) >= 2:
        column_count = len(table_rows[0])
        aligned_rows = [row for row in table_rows if len(row) == column_count]
        if len(aligned_rows) >= 2:
            source_rows = "\n".join("｜".join(row) for row in aligned_rows)
            return (
                f"\n表格视觉化硬约束：绘制一个统一的 {len(aligned_rows)} 行 {column_count} 列二维对比矩阵，"
                "共享同一组表头和对齐网格；同一行横向对比，同一列纵向归类。整个表格是一张完整信息图，"
                "不是多个互不相关的独立插画或文案卡片。把长句语义转成图标、物体、状态或关系，"
                "文字只保留表头、行名和必要短标签，不得逐字抄写长句；主角最多出现一次，只能在表格边缘辅助指示。\n"
                f"表格原文：\n{source_rows}"
            )

    flow_nodes = [node.strip() for node in _SCENE_FLOW_SPLIT_RE.split(scene) if node.strip()]
    if len(flow_nodes) >= 2:
        return (
            "\n顺序图硬约束：严格按从左到右的原始箭头顺序绘制，每个文本只对应一个节点；"
            "不得交换、合并、省略或新增节点，不得反转箭头；主角最多出现一次。\n"
            f"固定流程：{' -> '.join(flow_nodes)}"
        )
    return ""


def _single_character_reference_contract(reference_images: list[str] | None) -> str:
    if not reference_images:
        return ""
    return (
        "\n参考图解释硬约束：四张参考图属于同一只角色的不同视角，只用于锁定同一角色的轮廓、"
        "花色和配色，不代表四只角色。知识内容和信息结构必须占画面 80-90%；主角只是角落解说员，"
        "只占画面 10-20%，只能用视线、爪子或指示动作辅助讲解，不得替代流程节点、表格单元、结构框或对比关系。"
        "成图只能出现 1 只主角，不得复制、分身或在每个节点重复放置主角。"
    )


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


def _resolve_reference_image(image_ref: str) -> str:
    if image_ref.startswith(("http://", "https://", "data:")):
        return image_ref
    file_name = Path(image_ref).name
    local: Path | None = None
    if image_ref.startswith("/api/files/media/"):
        local = Path(get_settings().storage_dir) / "media" / file_name
    elif image_ref.startswith("/api/platforms/wechat-mp/illustration-characters/files/"):
        local = next((Path(get_settings().storage_dir) / "character-images").glob(f"u*/{file_name}"), None)
    if local is None or not local.is_file():
        raise ValueError("WeChat MP reference image is unavailable")
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(local.suffix.lower(), "image/png")
    return f"data:{mime};base64,{base64.b64encode(local.read_bytes()).decode()}"


def _call_image_model(
    *, prompt: str, model_name: str, size: str, base_url: str = "", api_key: str = "", reference_images: list[str] | None = None,
) -> dict[str, Any]:
    """Call the configured image provider; tests monkeypatch this narrow seam."""
    base_url = (base_url or os.getenv("WECHAT_MP_IMAGE_BASE_URL", "")).rstrip("/")
    api_key = api_key or os.getenv("WECHAT_MP_IMAGE_API_KEY", "")
    if not base_url or not api_key:
        raise ValueError("WeChat MP image model is not configured")
    try:
        body = {"model": model_name, "prompt": prompt, "size": size, "response_format": "url"}
        if reference_images:
            resolved = [_resolve_reference_image(item) for item in reference_images]
            body["image"] = resolved[0] if len(resolved) == 1 else resolved
            if len(resolved) > 1:
                body["sequential_image_generation"] = "disabled"
            body["watermark"] = False
        response = requests.post(
            f"{base_url}/images/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=180,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            try:
                payload = response.json()
                detail = payload.get("error", {}).get("message", "")
            except Exception:
                detail = ""
            raise ValueError(f"WeChat MP image model request failed: {detail or exc}") from exc
        provider_response = response.json()
        item = provider_response["data"][0]
        image_ref = item.get("url") or item.get("b64_json")
        if not isinstance(image_ref, str) or not image_ref:
            raise ValueError("image response missing url or b64_json")
    except requests.RequestException as exc:
        raise ValueError(f"WeChat MP image model request failed: {exc}") from exc
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("WeChat MP image model response is missing data[0].url") from exc
    return {"image_ref": image_ref, "provider_response": provider_response}


def _backfill_article_html(article: WechatMpArticle, prompt: WechatMpImagePrompt, section: WechatMpArticleSection, public_url: str) -> None:
    marker = f"{{{{image:prompt-{prompt.id}}}}}"
    alt_text = clean_markdown_plain_text(section.source_excerpt or section.summary) or "公众号正文配图"
    image_html = f'<img src="{escape(public_url, quote=True)}" alt="{escape(alt_text, quote=True)}" />'
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
    if prompt.quality_report and not prompt.quality_report.get("valid", False):
        raise WechatMpImageValidationError("Visual plan validation failed; fix the structure before image generation")

    from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model
    from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts

    from backend.app.services.wechat_mp_character_service import resolve_confirmed_character_anchor, resolve_prompt_character

    character, scene_prompt = resolve_prompt_character(
        db,
        user_id=user_id,
        default_skill_name=prompt.skill_name,
        text=prompt.editable_prompt,
        default_character_id=prompt.character_id,
    )
    anchor = resolve_confirmed_character_anchor(
        db, user_id=user_id, character_id=character.id if character else None, skill_name=None if character else prompt.skill_name,
    )
    reference_images = anchor[1] if anchor else None
    if character is not None:
        prompt.character_id = character.id
    if character is not None:
        scene_prompt = scene_prompt.strip()
        effective_prompt = f"{character.prompt}\n{scene_prompt if scene_prompt.startswith('具体画面：') else f'具体画面：{scene_prompt}'}"
    else:
        effective_prompt = scene_prompt
    effective_prompt = (
        f"{effective_prompt}{_structured_scene_contract(scene_prompt)}"
        f"{_single_character_reference_contract(reference_images)}"
    )
    from backend.app.services.wechat_mp_structured_image_service import (
        render_structured_image,
        supports_structured_render,
    )

    if supports_structured_render(prompt.visual_plan):
        result = render_structured_image(
            plan=prompt.visual_plan,
            user_id=user_id,
            reference_images=reference_images,
            output_dir=_media_dir(),
        )
        asset = WechatMpAsset(
            user_id=user_id,
            article_id=article.id,
            prompt_id=prompt.id,
            role="inline_illustration",
            file_path=result["file_path"],
            public_url=result["public_url"],
            prompt=effective_prompt,
            skill_name=prompt.skill_name,
            model_name=result["model_name"],
            status="generated",
            provider_response=result["provider_response"],
        )
        db.add(asset)
        prompt.status = "generated"
        _backfill_article_html(article, prompt, section, asset.public_url)
        invalidate_synced_drafts(db, article, next_status="images_partial")
        _update_article_image_state(db, article, prompt)
        db.commit()
        db.refresh(asset)
        return asset
    model = resolve_wechat_mp_model(
        db=db, user_id=user_id, model_type="image", requested_model=image_model,
    )
    normalized_size = normalize_illustration_size(model.model_name, size)
    # A text-similar asset from another character must never bypass a four-view anchor.
    reusable = None if reference_images else _find_reusable_asset(db, user_id=user_id, prompt=prompt)
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
            prompt=effective_prompt, model_name=model.model_name, size=normalized_size,
            base_url=model.base_url, api_key=model.api_key, reference_images=reference_images,
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
            prompt=effective_prompt,
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
    from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model
    from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts

    model = resolve_wechat_mp_model(
        db=db, user_id=user_id, model_type="image", requested_model=image_model,
    )
    normalized_size = normalize_illustration_size(model.model_name, size)
    from backend.app.services.wechat_mp_character_service import (
        NONE_SKILL_NAME,
        XIAOMAO_SKILL_NAME,
        canonicalize_character_prompt,
        resolve_character_by_skill,
        resolve_confirmed_character_anchor,
        resolve_prompt_character,
    )

    if article.illustration_skill == NONE_SKILL_NAME:
        prompt_text = canonicalize_character_prompt(
            None,
            article.cover_brief or article.title,
            include_character=False,
        )
        reference_images = None
    else:
        selected_character = resolve_character_by_skill(
            db,
            user_id=user_id,
            skill_name=article.illustration_skill,
        )
        character, scene_prompt = resolve_prompt_character(
            db,
            user_id=user_id,
            default_skill_name=article.illustration_skill,
            text=article.cover_brief or article.title,
            default_character_id=selected_character.id if selected_character is not None else None,
        )
        anchor = resolve_confirmed_character_anchor(
            db,
            user_id=user_id,
            character_id=character.id if character else None,
            skill_name=None if character else article.illustration_skill,
        )
        reference_images = anchor[1] if anchor is not None else None
        if character is not None:
            scene_prompt = scene_prompt.strip()
            scene_contract = scene_prompt if scene_prompt.startswith("具体画面：") else f"具体画面：{scene_prompt}"
            color_contract = (
                "严格继承参考图中的轮廓、黑白橙配色及橙斑位置，不得改成纯黑白或重新设计花色。"
                if character.skill_name == XIAOMAO_SKILL_NAME
                else "严格继承参考图中的轮廓、配色和特征位置，不得重新设计角色外观。"
            )
            prompt_text = (
                "微信公众号封面任务。\n"
                f"封面主题：{article.title}\n"
                f"{scene_contract}\n"
                "构图硬约束：把封面主题转译成清晰的可视化主体、结构或关系，主题结构占画面 80-90%；"
                "角色只占画面 10-20% 并作为角落解说员参与解释主题，不得只画角色，不得把标题文字直接画进图片。\n"
                f"角色一致性：{color_contract}\n"
                f"角色设定：{character.prompt}"
            )
        else:
            prompt_text = scene_prompt
    prompt_text = f"{prompt_text}{_single_character_reference_contract(reference_images)}"
    result = _call_image_model(
        prompt=prompt_text, model_name=model.model_name, size=normalized_size,
        base_url=model.base_url, api_key=model.api_key, reference_images=reference_images,
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
