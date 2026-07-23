from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import WechatMpArticle, WechatMpArticleSection


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
    del text_model  # Shot selection is deterministic; retained for the shared service interface.
    article = db.scalar(select(WechatMpArticle).where(WechatMpArticle.id == article_id, WechatMpArticle.user_id == user_id))
    if article is None:
        raise LookupError("WeChat MP article not found")
    if article.status not in {"layout_ready", "prompts_ready", "images_partial", "images_ready"}:
        raise ValueError("WeChat MP article must have a rendered layout before generating prompts")

    candidates = choose_candidate_sections(article.markdown_body)
    if not candidates:
        raise ValueError("WeChat MP article has no content for illustration prompts")

    existing_sections = {
        section.section_index: section
        for section in db.scalars(
            select(WechatMpArticleSection).where(WechatMpArticleSection.article_id == article.id)
        )
    }
    sections = []
    for candidate in candidates:
        section = existing_sections.get(candidate["section_index"])
        if section is None:
            section = WechatMpArticleSection(
                user_id=user_id,
                article_id=article.id,
                section_index=candidate["section_index"],
                summary=candidate["summary"],
                source_excerpt=candidate.get("source_excerpt", candidate["summary"]),
                needs_image=candidate["needs_image"],
            )
            db.add(section)
        else:
            section.summary = candidate["summary"]
            section.source_excerpt = candidate.get("source_excerpt", candidate["summary"])
            section.needs_image = candidate["needs_image"]
        sections.append(section)
    db.flush()
    return sections
