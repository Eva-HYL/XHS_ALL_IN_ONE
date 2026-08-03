from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import WechatMpArticle, WechatMpImagePrompt, WechatMpIllustrationCharacter
from backend.app.services.wechat_mp_character_service import (
    NONE_SKILL_NAME,
    XIAOMAO_CHARACTER_NAME,
    XIAOMAO_PROMPT,
    XIAOMAO_SKILL_NAME,
    format_character_prompt,
    resolve_character_by_skill,
)


_LEGACY_XIAOMAO_PROMPT_PREFIXES = (
    "白色背景，横向画幅，轻微抖动的手绘线稿，少量浅橙、红、蓝批注；"
    "主角必须是一只胖胖慵懒、半推半就但会把活干完的玳瑁猫，"
    "身体以黑白色块为主，背、头、尾点缀少量橙斑，半闭眼、冷淡表情；"
    "小猫自然趴卧并辅助表达画面核心概念，不穿衣、不画成可爱吉祥物；"
    "画面留白充足，一图一个核心结构，不使用写实摄影、3D 渲染、复杂背景或大段文字；"
    "不得渲染标题、比例、尺寸、提示词、说明文字、水印、签名或图中文字。",
    "白色背景，16:9 横版构图，轻微抖动的手绘线稿，少量浅橙、红、蓝批注；"
    "主角必须是一只胖胖慵懒、半推半就但会把活干完的玳瑁猫，"
    "身体以黑白色块为主，背、头、尾只有约 15-25% 小块橙斑，半闭眼、冷淡表情；"
    "小猫必须承担画面的核心概念动作，不能只做装饰，不穿衣、不直立、不画成可爱吉祥物；"
    "画面留白充足，一图一个核心结构，不使用写实摄影、3D 渲染、复杂背景或大段文字。",
)


def _strip_expanded_character_prefix(character: WechatMpIllustrationCharacter, text: str) -> str:
    prefixes = [character.prompt]
    if character.skill_name == XIAOMAO_SKILL_NAME:
        prefixes.extend((XIAOMAO_PROMPT, *_LEGACY_XIAOMAO_PROMPT_PREFIXES))
    cleaned = text.strip()
    for prefix in sorted(set(prefixes), key=len, reverse=True):
        if cleaned.startswith(prefix):
            return cleaned[len(prefix):].lstrip()
    return cleaned


def _format_stored_prompt(character: WechatMpIllustrationCharacter, text: str) -> str:
    return format_character_prompt(character, _strip_expanded_character_prefix(character, text))


def _resolve_character_by_skill(
    db: Session,
    *,
    user_id: int,
    skill_name: str,
) -> WechatMpIllustrationCharacter | None:
    character = db.scalar(select(WechatMpIllustrationCharacter).where(
        WechatMpIllustrationCharacter.user_id == user_id,
        WechatMpIllustrationCharacter.skill_name == skill_name,
    ))
    if character is None and skill_name == XIAOMAO_SKILL_NAME:
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
        return character
    return resolve_character_by_skill(db, user_id=user_id, skill_name=skill_name)


def _resolve_prompt_character(
    db: Session,
    prompt: WechatMpImagePrompt,
) -> WechatMpIllustrationCharacter | None:
    if prompt.character_id is not None:
        return db.scalar(select(WechatMpIllustrationCharacter).where(
            WechatMpIllustrationCharacter.id == prompt.character_id,
            WechatMpIllustrationCharacter.user_id == prompt.user_id,
        ))
    return _resolve_character_by_skill(db, user_id=prompt.user_id, skill_name=prompt.skill_name)


def backfill_character_mentions(db: Session, *, user_id: int | None = None) -> dict[str, int]:
    """Migrate stored character contracts to stable @mention references."""
    articles_query = select(WechatMpArticle).where(WechatMpArticle.illustration_skill != NONE_SKILL_NAME)
    if user_id is not None:
        articles_query = articles_query.where(WechatMpArticle.user_id == user_id)

    articles_updated = 0
    prompts_updated = 0
    for article in db.scalars(articles_query).all():
        character = _resolve_character_by_skill(
            db,
            user_id=article.user_id,
            skill_name=article.illustration_skill,
        )
        if character is not None:
            cover_brief = _format_stored_prompt(character, article.cover_brief)
            if cover_brief != article.cover_brief:
                article.cover_brief = cover_brief
                articles_updated += 1

        prompts = db.scalars(select(WechatMpImagePrompt).where(
            WechatMpImagePrompt.article_id == article.id,
        )).all()
        for prompt in prompts:
            prompt_character = _resolve_prompt_character(db, prompt)
            if prompt_character is None:
                continue
            normalized_prompt = _format_stored_prompt(prompt_character, prompt.prompt)
            normalized_editable_prompt = _format_stored_prompt(prompt_character, prompt.editable_prompt)
            if normalized_prompt == prompt.prompt and normalized_editable_prompt == prompt.editable_prompt:
                continue
            prompt.prompt = normalized_prompt
            prompt.editable_prompt = normalized_editable_prompt
            prompts_updated += 1

    db.commit()
    return {"articles_updated": articles_updated, "prompts_updated": prompts_updated}
