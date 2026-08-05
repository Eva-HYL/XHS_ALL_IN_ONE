from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal
from html import escape
from typing import TYPE_CHECKING, Any

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import WechatMpArticle, WechatMpArticleSection, WechatMpAsset, WechatMpImagePrompt
from backend.app.services.usage_recording_service import record_text_usage
from backend.app.services.wechat_mp_character_service import (
    NONE_SKILL_NAME,
    XIAOMAO_CHARACTER_NAME,
    XIAOMAO_PROMPT,
    XIAOMAO_SKILL_NAME,
    canonicalize_character_prompt,
    require_character_by_skill,
    resolve_character_by_skill,
)
from backend.app.services.wechat_mp_content_analysis_service import analyze_content
from backend.app.services.wechat_mp_cost_service import add_article_cost
from backend.app.services.wechat_mp_layout_service import render_wechat_html
from backend.app.services.wechat_mp_prompt_batch_service import generate_semantic_prompts
from backend.app.services.wechat_mp_prompt_ignore_service import filter_ignored_candidates
from backend.app.services.wechat_mp_visual_plan_service import build_visual_plan, compile_visual_prompt, validate_visual_plan
from backend.app.services.wechat_mp_shotlist_service import generate_article_shotlist

if TYPE_CHECKING:
    from backend.app.models.wechat_mp import WechatMpIllustrationCharacter
    from backend.app.services.wechat_mp_content_analysis_service import VisualCandidate


_PROMPT_SYSTEM = (
    "You write concise image prompts for Chinese WeChat article illustrations. Return only the image prompt. "
    "Never render prompt instructions, article titles, headings, aspect ratios, dimensions, captions, watermarks, "
    "or signatures as visible image text. Article and scene text is context only. If a diagram contract explicitly "
    "requires named nodes or labels, render only those exact labels and no other text."
)
_SKILL_VERSION = "v1.1.0"
_MAX_TOTAL_PROMPTS = 8
_MAX_SEMANTIC_PROMPTS = 6
_COST_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class WechatMpPromptGenerationAnalysis:
    source_blocks: int = 0
    filtered_blocks: int = 0
    deterministic_prompts: int = 0
    semantic_candidates: int = 0
    reused_prompts: int = 0
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class WechatMpPromptGenerationResult:
    items: list[WechatMpImagePrompt]
    analysis: WechatMpPromptGenerationAnalysis

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> WechatMpImagePrompt:
        return self.items[index]


class WechatMpPromptProviderError(RuntimeError):
    """A configured semantic provider was called but produced no usable result."""


def build_deterministic_prompt(candidate: "VisualCandidate", character: "WechatMpIllustrationCharacter | None") -> str:
    """Render only the analyzed structure and its canonical character mention."""
    plan = build_visual_plan(candidate)
    if candidate.kind not in {"flow", "table", "classification"}:
        raise ValueError("Candidate is not deterministic")
    return canonicalize_character_prompt(
        character,
        compile_visual_prompt(plan),
        include_character=character is not None,
    )


def generation_fingerprint(
    candidate: "VisualCandidate", *, character_id: int | None, anchor_version: int, skill_version: str,
) -> str:
    payload = {
        "anchor_version": anchor_version,
        "candidate": {
            "fingerprint": candidate.fingerprint,
            "kind": candidate.kind,
            "structure": candidate.structure,
        },
        "character_id": character_id,
        "skill_version": skill_version,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _fingerprint_skill_version(skill_name: str) -> str:
    return f"{skill_name}:{_SKILL_VERSION}"


def _find_current_candidate(article: WechatMpArticle, section: WechatMpArticleSection) -> "VisualCandidate | None":
    if not section.source_fingerprint:
        return None
    return next(
        (candidate for candidate in analyze_content(article.markdown_body).candidates if candidate.fingerprint == section.source_fingerprint),
        None,
    )


def build_skill_prompt(
    skill_name: str,
    article_title: str,
    section_summary: str,
    db: Session | None = None,
    user_id: int | None = None,
) -> str:
    character_name = XIAOMAO_CHARACTER_NAME if skill_name == XIAOMAO_SKILL_NAME else None
    if db is not None and user_id is not None and skill_name != NONE_SKILL_NAME:
        character = resolve_character_by_skill(db, user_id=user_id, skill_name=skill_name)
        character_name = character.name if character is not None else character_name
    diagram_contract = ""
    if "图解类型：" in section_summary:
        diagram_contract = (
            "\n图解硬约束：必须逐字保留图解节点、分类名称和顺序；"
            "优先画清晰的信息图、流程图、结构图或对比卡片；"
            "不要把流程改成泛化插画，不要省略箭头、节点或关键文字；"
            "主角形象只能作为角落辅助讲解，不得遮挡或替代图解主体。"
        )
    if character_name:
        character_contract = (
            f"主角引用：@{character_name}。只描述具体画面的动作、结构、关系和必要标签；"
            "不要重复角色外观、性格、画风、尺寸或禁用词。"
        )
        return f"{character_contract}{diagram_contract}\n文章：{article_title}\n场景：{section_summary}"
    return f"微信公众号正文插画。{diagram_contract}\n文章：{article_title}\n场景：{section_summary}"


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
    preserve_prompt_identity: bool = False,
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

    if preserve_prompt_identity:
        for prompt in prompts:
            prompt.status = "stale"
        article.html_body = cleaned_html
        return cleaned_html

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
    character = resolve_character_by_skill(db, user_id=user_id, skill_name=skill_name) if db is not None and user_id is not None else None
    stored_prompt = canonicalize_character_prompt(
        character,
        prompt,
        include_character=character is not None,
    )
    return {
        "prompt": stored_prompt,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model_name": model_name,
    }


def _selected_candidates(analysis) -> tuple["VisualCandidate", ...]:
    deterministic = analysis.deterministic_candidates[:_MAX_TOTAL_PROMPTS]
    remaining = _MAX_TOTAL_PROMPTS - len(deterministic)
    semantic = analysis.semantic_candidates[:min(_MAX_SEMANTIC_PROMPTS, remaining)]
    return (*deterministic, *semantic)


def _ensure_builtin_character_in_transaction(
    db: Session,
    user_id: int,
) -> "WechatMpIllustrationCharacter":
    from backend.app.models import WechatMpIllustrationCharacter

    character = db.scalar(select(WechatMpIllustrationCharacter).where(
        WechatMpIllustrationCharacter.user_id == user_id,
        WechatMpIllustrationCharacter.skill_name == XIAOMAO_SKILL_NAME,
    ))
    if character is None:
        character = WechatMpIllustrationCharacter(
            user_id=user_id,
            name=XIAOMAO_CHARACTER_NAME,
            skill_name=XIAOMAO_SKILL_NAME,
            prompt=XIAOMAO_PROMPT,
            status="draft",
            anchor_version=1,
        )
        db.add(character)
        db.flush()
    elif character.name != XIAOMAO_CHARACTER_NAME:
        character.name = XIAOMAO_CHARACTER_NAME
    return character


def _remove_asset_image(html_body: str, public_url: str) -> str:
    image_pattern = re.compile(
        r'<img\b[^>]*\bsrc=["\']' + re.escape(escape(public_url, quote=True)) + r'["\'][^>]*>'
    )
    return image_pattern.sub("", html_body)


def _has_embedded_generated_asset(
    db: Session, article: WechatMpArticle, prompt: WechatMpImagePrompt,
) -> bool:
    assets = db.scalars(select(WechatMpAsset).where(
        WechatMpAsset.user_id == article.user_id,
        WechatMpAsset.article_id == article.id,
        WechatMpAsset.prompt_id == prompt.id,
        WechatMpAsset.role == "inline_illustration",
        WechatMpAsset.status == "generated",
        WechatMpAsset.public_url != "",
    )).all()
    return any(
        re.search(
            r'<img\b[^>]*\bsrc=["\']' + re.escape(escape(asset.public_url, quote=True)) + r'["\'][^>]*>',
            article.html_body,
        )
        for asset in assets
    )


def _delete_prompt_state(db: Session, article: WechatMpArticle, prompt: WechatMpImagePrompt) -> None:
    article.html_body = article.html_body.replace(f"{{{{image:prompt-{prompt.id}}}}}", "")
    for asset in db.scalars(select(WechatMpAsset).where(
        WechatMpAsset.user_id == article.user_id,
        WechatMpAsset.article_id == article.id,
        WechatMpAsset.prompt_id == prompt.id,
    )).all():
        article.html_body = _remove_asset_image(article.html_body, asset.public_url)
        asset.prompt_id = None
    db.delete(prompt)


def _delete_section_state(db: Session, article: WechatMpArticle, section: WechatMpArticleSection) -> None:
    for prompt in db.scalars(select(WechatMpImagePrompt).where(
        WechatMpImagePrompt.user_id == article.user_id,
        WechatMpImagePrompt.article_id == article.id,
        WechatMpImagePrompt.section_id == section.id,
    )).all():
        _delete_prompt_state(db, article, prompt)
    db.delete(section)


def _clean_detached_inline_state(
    db: Session,
    article: WechatMpArticle,
    retained_prompt_ids: set[int],
    previously_linked_asset_ids: set[int],
) -> None:
    article.html_body = re.sub(
        r"\{\{image:prompt-(\d+)\}\}",
        lambda match: match.group(0) if int(match.group(1)) in retained_prompt_ids else "",
        article.html_body,
    )
    if not previously_linked_asset_ids:
        return
    for asset in db.scalars(select(WechatMpAsset).where(
        WechatMpAsset.id.in_(previously_linked_asset_ids),
        WechatMpAsset.prompt_id.is_(None),
    )).all():
        article.html_body = _remove_asset_image(article.html_body, asset.public_url)


def _allocate_cost(total: Decimal, count: int) -> list[Decimal]:
    if count <= 0:
        return []
    total = Decimal(total).quantize(_COST_QUANTUM)
    units = int(total / _COST_QUANTUM)
    base_units, remainder = divmod(units, count)
    allocations = [_COST_QUANTUM * base_units for _ in range(count)]
    allocations[-1] += _COST_QUANTUM * remainder
    return allocations


def generate_image_prompts(
    *, db: Session, user_id: int, article_id: int, skill_name: str | None,
) -> WechatMpPromptGenerationResult:
    article = db.scalar(select(WechatMpArticle).where(
        WechatMpArticle.id == article_id,
        WechatMpArticle.user_id == user_id,
    ))
    if article is None:
        raise LookupError("WeChat MP article not found")
    if article.status not in {"layout_ready", "prompts_ready", "images_partial", "images_ready"}:
        raise ValueError("WeChat MP article must have a rendered layout before generating prompts")

    selected_skill = skill_name or article.illustration_skill or XIAOMAO_SKILL_NAME
    if selected_skill == XIAOMAO_SKILL_NAME:
        selected_character = _ensure_builtin_character_in_transaction(db, user_id)
    else:
        selected_character = require_character_by_skill(
            db,
            user_id=user_id,
            skill_name=selected_skill,
        )
    content_analysis = analyze_content(article.markdown_body)
    selected_candidates = () if selected_skill == NONE_SKILL_NAME else _selected_candidates(content_analysis)
    candidates, ignored_matches = filter_ignored_candidates(
        db, user_id=user_id, candidates=selected_candidates,
    )
    analysis_values = {
        "source_blocks": len(content_analysis.blocks),
        "filtered_blocks": content_analysis.filtered_blocks + len(ignored_matches),
        "deterministic_prompts": sum(candidate.kind != "semantic" for candidate in candidates),
        "semantic_candidates": sum(candidate.kind == "semantic" for candidate in candidates),
        "reused_prompts": 0,
        "model_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    original_html = article.html_body
    original_skill = article.illustration_skill
    existing_prompt_ids = set(db.scalars(
        select(WechatMpImagePrompt.id).where(WechatMpImagePrompt.article_id == article.id)
    ).all())
    existing_prompt_versions = dict(db.execute(
        select(WechatMpImagePrompt.id, WechatMpImagePrompt.version).where(
            WechatMpImagePrompt.article_id == article.id
        )
    ).all())
    existing_prompt_statuses = dict(db.execute(
        select(WechatMpImagePrompt.id, WechatMpImagePrompt.status).where(
            WechatMpImagePrompt.article_id == article.id
        )
    ).all())
    existing_section_ids = set(db.scalars(
        select(WechatMpArticleSection.id).where(WechatMpArticleSection.article_id == article.id)
    ).all())
    previously_linked_asset_ids = set(db.scalars(select(WechatMpAsset.id).where(
        WechatMpAsset.article_id == article.id,
        WechatMpAsset.role == "inline_illustration",
        WechatMpAsset.prompt_id.is_not(None),
    )).all())

    try:
        if not candidates:
            if ignored_matches:
                db.commit()
                ignored_prompts = db.scalars(select(WechatMpImagePrompt).where(
                    WechatMpImagePrompt.article_id == article.id,
                    WechatMpImagePrompt.user_id == user_id,
                    WechatMpImagePrompt.status == "ignored",
                )).all()
                return WechatMpPromptGenerationResult(
                    items=ignored_prompts,
                    analysis=WechatMpPromptGenerationAnalysis(**analysis_values),
                )
            if existing_prompt_ids or existing_section_ids or "{{image:prompt-" in article.html_body:
                reset_inline_illustrations(db, article)
            article.illustration_skill = selected_skill
            changed = (
                original_skill != selected_skill
                or original_html != article.html_body
                or bool(existing_prompt_ids)
                or bool(existing_section_ids)
            )
            if changed:
                from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts

                invalidate_synced_drafts(db, article, next_status="layout_ready")
            db.commit()
            return WechatMpPromptGenerationResult(
                items=[], analysis=WechatMpPromptGenerationAnalysis(**analysis_values),
            )

        all_sections = generate_article_shotlist(
            db=db, user_id=user_id, article_id=article_id, text_model="deterministic",
        )
        sections_by_candidate: dict[tuple[str, int], deque[WechatMpArticleSection]] = defaultdict(deque)
        for section in all_sections:
            candidate = getattr(section, "_visual_candidate", None)
            if candidate is not None:
                sections_by_candidate[(candidate.fingerprint, candidate.source_index)].append(section)
        active_sections: list[tuple[WechatMpArticleSection, "VisualCandidate"]] = []
        for candidate in candidates:
            matching = sections_by_candidate[(candidate.fingerprint, candidate.source_index)]
            if matching:
                active_sections.append((matching.popleft(), candidate))
        active_section_ids = {section.id for section, _ in active_sections}
        ignored_section_ids = set(db.scalars(select(WechatMpImagePrompt.section_id).where(
            WechatMpImagePrompt.article_id == article.id,
            WechatMpImagePrompt.status == "ignored",
        )).all())
        for section in all_sections:
            if section.id not in active_section_ids and section.id not in ignored_section_ids:
                _delete_section_state(db, article, section)
        pre_generation_prompt_ids = set(db.scalars(
            select(WechatMpImagePrompt.id).where(WechatMpImagePrompt.article_id == article.id)
        ).all())
        for obsolete_prompt_id in existing_prompt_ids - pre_generation_prompt_ids:
            article.html_body = article.html_body.replace(
                f"{{{{image:prompt-{obsolete_prompt_id}}}}}", "",
            )

        prompts_by_section: dict[int, WechatMpImagePrompt] = {}
        unresolved_semantic: list[tuple[WechatMpArticleSection, "VisualCandidate", WechatMpImagePrompt | None, str]] = []
        fingerprint_skill_version = _fingerprint_skill_version(selected_skill)
        character_id = selected_character.id if selected_character else None
        anchor_version = selected_character.anchor_version if selected_character else 0
        for section, candidate in active_sections:
            visual_plan = build_visual_plan(candidate)
            quality_report = validate_visual_plan(candidate, visual_plan)
            fingerprint = generation_fingerprint(
                candidate,
                character_id=character_id,
                anchor_version=anchor_version,
                skill_version=fingerprint_skill_version,
            )
            sibling_prompts = db.scalars(
                select(WechatMpImagePrompt)
                .where(
                    WechatMpImagePrompt.user_id == user_id,
                    WechatMpImagePrompt.article_id == article.id,
                    WechatMpImagePrompt.section_id == section.id,
                )
                .order_by(WechatMpImagePrompt.id.desc())
            ).all()
            prompt = sibling_prompts[0] if sibling_prompts else None
            for sibling in sibling_prompts[1:]:
                _delete_prompt_state(db, article, sibling)
            reusable = (
                prompt is not None
                and prompt.generation_fingerprint == fingerprint
                and prompt.skill_name == selected_skill
                and prompt.character_id == character_id
                and prompt.skill_version == _SKILL_VERSION
            )
            if reusable:
                prompt.visual_plan = visual_plan
                prompt.quality_report = quality_report
                has_embedded_asset = _has_embedded_generated_asset(db, article, prompt)
                if prompt.status == "generated" and has_embedded_asset:
                    article.html_body = article.html_body.replace(
                        f"{{{{image:prompt-{prompt.id}}}}}", "",
                    )
                else:
                    _restore_prompt_placeholder(db, article, section, prompt)
                    prompt.status = "prompt_ready"
                prompt.cost_estimate = {"currency": "CNY", "total_yuan": "0.0000", "calls": 0}
                prompts_by_section[section.id] = prompt
                analysis_values["reused_prompts"] += 1
                continue
            if candidate.kind == "semantic":
                unresolved_semantic.append((section, candidate, prompt, fingerprint))
                continue

            prompt_text = build_deterministic_prompt(candidate, selected_character)
            if prompt is None:
                prompt = WechatMpImagePrompt(
                    user_id=user_id,
                    article_id=article.id,
                    section_id=section.id,
                    character_id=character_id,
                    skill_name=selected_skill,
                    prompt=prompt_text,
                    editable_prompt=prompt_text,
                    generation_fingerprint=fingerprint,
                    skill_version=_SKILL_VERSION,
                    version=1,
                    status="prompt_ready",
                    visual_plan=visual_plan,
                    quality_report=quality_report,
                )
                db.add(prompt)
                db.flush()
            else:
                _restore_prompt_placeholder(db, article, section, prompt)
                prompt.character_id = character_id
                prompt.skill_name = selected_skill
                prompt.prompt = prompt_text
                prompt.editable_prompt = prompt_text
                prompt.generation_fingerprint = fingerprint
                prompt.skill_version = _SKILL_VERSION
                prompt.version += 1
                prompt.status = "prompt_ready"
                prompt.visual_plan = visual_plan
                prompt.quality_report = quality_report
            prompt.cost_estimate = {"currency": "CNY", "total_yuan": "0.0000", "calls": 0}
            _insert_prompt_placeholder(article, section, prompt)
            prompts_by_section[section.id] = prompt

        semantic_prompts: list[WechatMpImagePrompt] = []
        if unresolved_semantic:
            batch_result = generate_semantic_prompts(
                db=db,
                user_id=user_id,
                article_title=article.title,
                candidates=[candidate for _, candidate, _, _ in unresolved_semantic],
                character=selected_character,
            )
            analysis_values.update({
                "model_calls": batch_result.model_calls,
                "input_tokens": batch_result.input_tokens,
                "output_tokens": batch_result.output_tokens,
            })
            batch_items = {item.candidate_id: item.prompt for item in batch_result.items}
            for section, candidate, prompt, fingerprint in unresolved_semantic:
                visual_plan = build_visual_plan(candidate)
                quality_report = validate_visual_plan(candidate, visual_plan)
                generated_prompt = batch_items.get(str(candidate.source_index))
                if generated_prompt is None:
                    continue
                prompt_text = canonicalize_character_prompt(
                    selected_character,
                    generated_prompt,
                    include_character=selected_character is not None,
                )
                if prompt is None:
                    prompt = WechatMpImagePrompt(
                        user_id=user_id,
                        article_id=article.id,
                        section_id=section.id,
                        character_id=character_id,
                        skill_name=selected_skill,
                        prompt=prompt_text,
                        editable_prompt=prompt_text,
                        generation_fingerprint=fingerprint,
                        skill_version=_SKILL_VERSION,
                        version=1,
                        status="prompt_ready",
                        visual_plan=visual_plan,
                        quality_report=quality_report,
                    )
                    db.add(prompt)
                    db.flush()
                else:
                    _restore_prompt_placeholder(db, article, section, prompt)
                    prompt.character_id = character_id
                    prompt.skill_name = selected_skill
                    prompt.prompt = prompt_text
                    prompt.editable_prompt = prompt_text
                    prompt.generation_fingerprint = fingerprint
                    prompt.skill_version = _SKILL_VERSION
                    prompt.version += 1
                    prompt.status = "prompt_ready"
                    prompt.visual_plan = visual_plan
                    prompt.quality_report = quality_report
                _insert_prompt_placeholder(article, section, prompt)
                prompts_by_section[section.id] = prompt
                semantic_prompts.append(prompt)

            if batch_result.model_calls and batch_result.model_name:
                usage = record_text_usage(
                    db=db,
                    user_id=user_id,
                    pipeline_run_id=None,
                    step="generate_image_prompts_batch",
                    model=batch_result.model_name,
                    input_tokens=batch_result.input_tokens,
                    output_tokens=batch_result.output_tokens,
                    platform="wechat_mp",
                    resource_type="wechat_mp_article",
                    resource_id=article.id,
                    commit=False,
                )
                allocations = _allocate_cost(usage.cost_yuan, len(semantic_prompts))
                for index, (prompt, cost) in enumerate(zip(semantic_prompts, allocations, strict=True)):
                    prompt.cost_estimate = {
                        "currency": "CNY",
                        "total_yuan": f"{cost:.4f}",
                        "calls": batch_result.model_calls if index == 0 else 0,
                    }
                add_article_cost(article, usage.cost_yuan)

            has_deterministic_result = any(
                candidate.kind != "semantic" and section.id in prompts_by_section
                for section, candidate in active_sections
            )
            if (
                batch_result.outcome == "provider_failed"
                and not semantic_prompts
                and not has_deterministic_result
            ):
                raise WechatMpPromptProviderError(
                    "WeChat MP prompt provider failed without a deterministic result"
                )

            resolved_semantic_ids = {prompt.section_id for prompt in semantic_prompts}
            for section, _, prompt, _ in unresolved_semantic:
                if section.id not in resolved_semantic_ids and prompt is not None:
                    _delete_prompt_state(db, article, prompt)

        ordered_prompts = [
            prompts_by_section[section.id]
            for section, _ in active_sections
            if section.id in prompts_by_section
        ]
        retained_prompt_ids = {prompt.id for prompt in ordered_prompts}
        _clean_detached_inline_state(
            db, article, retained_prompt_ids, previously_linked_asset_ids,
        )
        article.illustration_skill = selected_skill
        db.flush()
        current_prompt_ids = set(db.scalars(
            select(WechatMpImagePrompt.id).where(WechatMpImagePrompt.article_id == article.id)
        ).all())
        current_section_ids = set(db.scalars(
            select(WechatMpArticleSection.id).where(WechatMpArticleSection.article_id == article.id)
        ).all())
        current_prompt_statuses = dict(db.execute(
            select(WechatMpImagePrompt.id, WechatMpImagePrompt.status).where(
                WechatMpImagePrompt.article_id == article.id
            )
        ).all())
        changed = (
            original_skill != selected_skill
            or original_html != article.html_body
            or existing_prompt_ids != current_prompt_ids
            or existing_section_ids != current_section_ids
            or existing_prompt_statuses != current_prompt_statuses
            or any(existing_prompt_versions.get(prompt.id) != prompt.version for prompt in ordered_prompts)
        )
        if changed:
            from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts

            invalidate_synced_drafts(db, article, next_status="prompts_ready" if ordered_prompts else "layout_ready")
        db.commit()
    except Exception:
        db.rollback()
        raise

    for prompt in ordered_prompts:
        db.refresh(prompt)
    return WechatMpPromptGenerationResult(
        items=ordered_prompts,
        analysis=WechatMpPromptGenerationAnalysis(**analysis_values),
    )


def regenerate_image_prompt(*, db: Session, prompt: WechatMpImagePrompt, article: WechatMpArticle) -> WechatMpImagePrompt:
    section = db.get(WechatMpArticleSection, prompt.section_id)
    if section is None or section.article_id != article.id:
        raise LookupError("WeChat MP prompt not found")
    character = require_character_by_skill(
        db,
        user_id=article.user_id,
        skill_name=prompt.skill_name,
    )
    candidate = _find_current_candidate(article, section)
    is_deterministic = candidate is not None and candidate.kind != "semantic"

    if prompt.skill_name == NONE_SKILL_NAME:
        result = {
            "prompt": prompt.editable_prompt,
            "input_tokens": 0,
            "output_tokens": 0,
            "model_name": "deterministic",
        }
    elif is_deterministic:
        result = {
            "prompt": build_deterministic_prompt(candidate, character),
            "input_tokens": 0,
            "output_tokens": 0,
            "model_name": "deterministic",
        }
    else:
        from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model
        model = resolve_wechat_mp_model(db=db, user_id=article.user_id, model_type="text")
        result = _call_prompt_model(
            article_title=article.title,
            section_summary=section.summary,
            skill_name=prompt.skill_name,
            model_name=model.model_name,
            base_url=model.base_url,
            api_key=model.api_key,
            db=db,
            user_id=article.user_id,
        )
    result["prompt"] = canonicalize_character_prompt(
        character,
        result["prompt"],
        include_character=character is not None,
    )
    prompt.prompt = result["prompt"]
    prompt.editable_prompt = result["prompt"]
    if candidate is not None:
        prompt.generation_fingerprint = generation_fingerprint(
            candidate,
            character_id=character.id if character else None,
            anchor_version=character.anchor_version if character else 0,
            skill_version=_fingerprint_skill_version(prompt.skill_name),
        )
    prompt.skill_version = _SKILL_VERSION
    prompt.version += 1
    prompt.status = "skipped" if prompt.skill_name == NONE_SKILL_NAME else "prompt_ready"
    if prompt.skill_name != NONE_SKILL_NAME:
        _restore_prompt_placeholder(db, article, section, prompt)
    if prompt.skill_name == NONE_SKILL_NAME or is_deterministic:
        prompt.cost_estimate = {"currency": "CNY", "total_yuan": "0.0000", "calls": 0}
    else:
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
