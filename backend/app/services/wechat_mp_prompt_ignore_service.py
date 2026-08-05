from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    WechatMpArticle,
    WechatMpArticleSection,
    WechatMpAsset,
    WechatMpImagePrompt,
    WechatMpPromptIgnoreRule,
)


_CONCEPT_SPLIT_RE = re.compile(r"\s*(?:→|->|\||｜|、|，|,|；|;|：|:|\+|/|\\n)\s*")
_GENERIC_CONCEPTS = {"内容", "要点", "过程", "流程", "对比项", "范围管理六过程"}


@dataclass(frozen=True)
class ConceptSignature:
    kind: str
    concepts: frozenset[str]


def _normalize_concept(value: str) -> str:
    value = re.sub(r"[*_`#]", "", value).strip().lower()
    return re.sub(r"\s+", "", value)


def build_concept_signature(text: str, kind: str) -> ConceptSignature:
    concepts = {
        normalized
        for part in _CONCEPT_SPLIT_RE.split(text)
        if (normalized := _normalize_concept(part)) and normalized not in _GENERIC_CONCEPTS
    }
    return ConceptSignature(kind=kind, concepts=frozenset(concepts))


def concept_similarity(left: ConceptSignature, right: ConceptSignature) -> float:
    if not left.concepts or not right.concepts:
        return 0.0
    shared = left.concepts & right.concepts
    return len(shared) / min(len(left.concepts), len(right.concepts))


def _candidate_signature(candidate) -> ConceptSignature:
    text = "\n".join(" | ".join(row) for row in candidate.structure)
    return build_concept_signature(text, candidate.kind)


def _serialize_signature(signature: ConceptSignature) -> dict:
    return {"kind": signature.kind, "concepts": sorted(signature.concepts)}


def _deserialize_signature(payload: dict) -> ConceptSignature:
    return ConceptSignature(
        kind=str(payload.get("kind") or "semantic"),
        concepts=frozenset(str(item) for item in payload.get("concepts", []) if str(item)),
    )


def filter_ignored_candidates(db: Session, *, user_id: int, candidates: tuple) -> tuple[tuple, dict[str, int]]:
    rules = db.scalars(select(WechatMpPromptIgnoreRule).where(
        WechatMpPromptIgnoreRule.user_id == user_id,
        WechatMpPromptIgnoreRule.status == "active",
    )).all()
    kept = []
    matched: dict[str, int] = {}
    for candidate in candidates:
        signature = _candidate_signature(candidate)
        rule = next(
            (
                item for item in rules
                if concept_similarity(signature, _deserialize_signature(item.concept_signature)) >= 0.78
            ),
            None,
        )
        if rule is None:
            kept.append(candidate)
        else:
            matched[candidate.fingerprint] = rule.id
    return tuple(kept), matched


def ignore_prompt(
    db: Session, *, user_id: int, article_id: int, prompt_id: int, future_similar: bool,
) -> WechatMpImagePrompt:
    prompt = db.scalar(select(WechatMpImagePrompt).where(
        WechatMpImagePrompt.id == prompt_id,
        WechatMpImagePrompt.article_id == article_id,
        WechatMpImagePrompt.user_id == user_id,
    ))
    article = db.scalar(select(WechatMpArticle).where(
        WechatMpArticle.id == article_id,
        WechatMpArticle.user_id == user_id,
    ))
    if prompt is None or article is None:
        raise LookupError("WeChat MP prompt not found")
    section = db.get(WechatMpArticleSection, prompt.section_id)
    if section is None or section.article_id != article.id:
        raise LookupError("WeChat MP prompt not found")

    from backend.app.services.wechat_mp_image_prompt_service import _remove_asset_image

    article.html_body = article.html_body.replace(f"{{{{image:prompt-{prompt.id}}}}}", "")
    for asset in db.scalars(select(WechatMpAsset).where(
        WechatMpAsset.article_id == article.id,
        WechatMpAsset.prompt_id == prompt.id,
    )).all():
        article.html_body = _remove_asset_image(article.html_body, asset.public_url)
    prompt.status = "ignored"

    if future_similar:
        source_text = section.source_excerpt or prompt.editable_prompt
        signature = build_concept_signature(source_text, str(prompt.visual_plan.get("kind") or "semantic"))
        existing = db.scalars(select(WechatMpPromptIgnoreRule).where(
            WechatMpPromptIgnoreRule.user_id == user_id,
            WechatMpPromptIgnoreRule.status == "active",
        )).all()
        if not any(concept_similarity(signature, _deserialize_signature(rule.concept_signature)) >= 0.99 for rule in existing):
            db.add(WechatMpPromptIgnoreRule(
                user_id=user_id,
                source_article_id=article.id,
                source_prompt_id=prompt.id,
                candidate_kind=signature.kind,
                source_text=source_text,
                concept_signature=_serialize_signature(signature),
                status="active",
            ))
    from backend.app.services.wechat_mp_revision_service import invalidate_synced_drafts

    invalidate_synced_drafts(db, article, next_status="prompts_ready")
    db.commit()
    db.refresh(prompt)
    return prompt


def restore_prompt(db: Session, *, user_id: int, article_id: int, prompt_id: int) -> WechatMpImagePrompt:
    prompt = db.scalar(select(WechatMpImagePrompt).where(
        WechatMpImagePrompt.id == prompt_id,
        WechatMpImagePrompt.article_id == article_id,
        WechatMpImagePrompt.user_id == user_id,
    ))
    article = db.scalar(select(WechatMpArticle).where(
        WechatMpArticle.id == article_id,
        WechatMpArticle.user_id == user_id,
    ))
    if prompt is None or article is None:
        raise LookupError("WeChat MP prompt not found")
    section = db.get(WechatMpArticleSection, prompt.section_id)
    if section is None or section.article_id != article.id:
        raise LookupError("WeChat MP prompt not found")
    from backend.app.services.wechat_mp_image_prompt_service import _restore_prompt_placeholder

    prompt.status = "prompt_ready"
    _restore_prompt_placeholder(db, article, section, prompt)
    db.commit()
    db.refresh(prompt)
    return prompt
