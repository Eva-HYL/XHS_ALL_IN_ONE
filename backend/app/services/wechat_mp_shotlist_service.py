from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import WechatMpArticle, WechatMpArticleSection, WechatMpAsset, WechatMpImagePrompt
from backend.app.services.wechat_mp_content_analysis_service import VisualCandidate, analyze_content


_ANCHOR_WORDS = ("关键", "转折", "方法", "问题", "结果", "口诀", "必考", "高频")
_FLOW_SPLIT_RE = re.compile(r"\s*(?:→|->|⇒|=>|＞|>)\s*")


def _is_heading(paragraph: str) -> bool:
    return paragraph.startswith(("# ", "## ", "### ")) or bool(re.fullmatch(r"\d+(?:\.\d+)*\s+.{1,40}", paragraph))


def _extract_flow_nodes(paragraph: str) -> list[str]:
    if not any(marker in paragraph for marker in ("→", "->", "=>", "⇒", ">", "＞")):
        return []
    text = re.sub(r"^[\s\-*#\d.、：:]+", "", paragraph.strip())
    nodes = [node.strip(" 。；;，,：:") for node in _FLOW_SPLIT_RE.split(text) if node.strip(" 。；;，,：:")]
    return nodes if len(nodes) >= 3 else []


def _diagram_summary(paragraph: str) -> tuple[int, str] | None:
    flow_nodes = _extract_flow_nodes(paragraph)
    if flow_nodes:
        return (
            0,
            "图解类型：流程图\n"
            f"必须准确呈现节点：{' -> '.join(flow_nodes)}\n"
            "要求：按从左到右的箭头顺序画出节点，不增删、不改名。\n"
            f"原文：{paragraph[:220]}",
        )
    if "|" in paragraph and re.search(r"\|.*\|", paragraph):
        return (
            1,
            "图解类型：对比表/分类卡片\n"
            "要求：保留表格中的分类名称和对应关系，画成清晰信息图，不要虚构内容。\n"
            f"原文：{paragraph[:220]}",
        )
    if re.search(r"(三种|三大|五种|五级|分类|层次|级别|模型|视图|指标)", paragraph):
        return (
            2,
            "图解类型：分类结构图\n"
            "要求：提取原文中的类别、层次或指标，画成结构化知识卡，不要只画装饰插图。\n"
            f"原文：{paragraph[:220]}",
        )
    return None


def choose_candidate_sections(markdown_body: str) -> list[dict]:
    paragraphs = [paragraph.strip() for paragraph in markdown_body.split("\n\n") if paragraph.strip()]
    if not paragraphs:
        return []

    selected: list[tuple[int, int, dict]] = []
    fallback: list[tuple[int, int, dict]] = []
    for index, paragraph in enumerate(paragraphs):
        diagram = _diagram_summary(paragraph)
        if diagram is not None:
            priority, summary = diagram
            selected.append((
                priority,
                index,
                {
                    "section_index": index,
                    "summary": summary,
                    "source_excerpt": paragraph,
                    "needs_image": True,
                },
            ))
            continue
        if not _is_heading(paragraph) and any(word in paragraph for word in _ANCHOR_WORDS):
            fallback.append((
                5,
                index,
                {
                    "section_index": index,
                    "summary": paragraph[:180],
                    "source_excerpt": paragraph,
                    "needs_image": True,
                },
            ))
    ranked = [item for _, _, item in sorted(selected + fallback, key=lambda item: (item[0], item[1]))]
    return ranked[:8] or [{
        "section_index": 0,
        "summary": paragraphs[0][:180],
        "source_excerpt": paragraphs[0],
        "needs_image": True,
    }]


def generate_article_shotlist(*, db: Session, user_id: int, article_id: int, text_model: str) -> list[WechatMpArticleSection]:
    del text_model  # Retained for the shared service interface.
    article = db.scalar(select(WechatMpArticle).where(WechatMpArticle.id == article_id, WechatMpArticle.user_id == user_id))
    if article is None:
        raise LookupError("WeChat MP article not found")
    if article.status not in {"layout_ready", "prompts_ready", "images_partial", "images_ready"}:
        raise ValueError("WeChat MP article must have a rendered layout before generating prompts")

    analysis = analyze_content(article.markdown_body)
    candidates = list(analysis.candidates)
    if not candidates:
        # Keep legacy short-form articles usable while retaining analyzer-owned blocks/fingerprints.
        blocks_by_text = {block.raw_text: block for block in analysis.blocks}
        for item in choose_candidate_sections(article.markdown_body):
            block = blocks_by_text.get(item["source_excerpt"])
            if block is None:
                block = next(
                    (record for record in analysis.blocks if record.raw_text and record.raw_text in item["source_excerpt"]),
                    None,
                )
            if block is not None:
                candidates.append(VisualCandidate(block=block, kind="semantic", structure=(), score=0.0))
    if not candidates:
        raise ValueError("WeChat MP article has no content for illustration prompts")

    existing_sections = db.scalars(
        select(WechatMpArticleSection).where(WechatMpArticleSection.article_id == article.id)
    ).all()
    existing_by_fingerprint = {
        section.source_fingerprint: section
        for section in existing_sections
        if section.source_fingerprint
    }
    legacy_by_index = {
        section.section_index: section
        for section in existing_sections
        if not section.source_fingerprint
    }
    sections = []
    for candidate in candidates:
        section = existing_by_fingerprint.get(candidate.fingerprint) or legacy_by_index.get(candidate.source_index)
        if section is None:
            section = WechatMpArticleSection(
                user_id=user_id,
                article_id=article.id,
                section_index=candidate.source_index,
                summary=candidate.block.cleaned_text,
                source_excerpt=candidate.block.raw_text,
                source_fingerprint=candidate.fingerprint,
                analysis_version=analysis.analysis_version,
                needs_image=True,
            )
            db.add(section)
        else:
            section.section_index = candidate.source_index
            section.summary = candidate.block.cleaned_text
            section.source_excerpt = candidate.block.raw_text
            section.source_fingerprint = candidate.fingerprint
            section.analysis_version = analysis.analysis_version
            section.needs_image = True
        # This transient link keeps prompt rendering tied to the analyzed structure.
        section._visual_candidate = candidate
        sections.append(section)

    matched_section_ids = {section.id for section in sections if section.id is not None}
    for section in existing_sections:
        if section.id in matched_section_ids:
            continue
        for prompt in db.scalars(
            select(WechatMpImagePrompt).where(WechatMpImagePrompt.section_id == section.id)
        ):
            for asset in db.scalars(select(WechatMpAsset).where(WechatMpAsset.prompt_id == prompt.id)):
                asset.prompt_id = None
            db.delete(prompt)
        db.delete(section)
    db.flush()
    return sections
