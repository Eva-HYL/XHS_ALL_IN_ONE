from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import WechatMpArticle, WechatMpArticleSection


_ANCHOR_WORDS = ("关键", "转折", "方法", "问题", "结果")


def choose_candidate_sections(markdown_body: str) -> list[dict]:
    paragraphs = [paragraph.strip() for paragraph in markdown_body.split("\n\n") if paragraph.strip()]
    if not paragraphs:
        return []

    selected = []
    for index, paragraph in enumerate(paragraphs):
        if paragraph.startswith("## ") or any(word in paragraph for word in _ANCHOR_WORDS):
            selected.append({"section_index": index, "summary": paragraph[:180], "needs_image": True})
    return selected[:8] or [{"section_index": 0, "summary": paragraphs[0][:180], "needs_image": True}]


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
                source_excerpt=candidate["summary"],
                needs_image=candidate["needs_image"],
            )
            db.add(section)
        else:
            section.summary = candidate["summary"]
            section.source_excerpt = candidate["summary"]
            section.needs_image = candidate["needs_image"]
        sections.append(section)
    db.flush()
    return sections
