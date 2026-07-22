from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import WechatMpIllustrationCharacter


XIAOMAO_SKILL_NAME = "xiaomao-illustrations"
NONE_SKILL_NAME = "none"
XIAOMAO_PROMPT = (
    "白色背景，16:9 横版构图，轻微抖动的手绘线稿，少量浅橙、红、蓝批注；"
    "主角必须是一只胖胖慵懒、半推半就但会把活干完的玳瑁猫，"
    "身体以黑白色块为主，背、头、尾只有约 15-25% 小块橙斑，半闭眼、冷淡表情；"
    "小猫必须承担画面的核心概念动作，不能只做装饰，不穿衣、不直立、不画成可爱吉祥物；"
    "画面留白充足，一图一个核心结构，不使用写实摄影、3D 渲染、复杂背景或大段文字。"
)


def builtin_characters() -> list[dict]:
    now = datetime.utcnow()
    return [
        {
            "id": None,
            "user_id": None,
            "name": "小猫插画",
            "skill_name": XIAOMAO_SKILL_NAME,
            "prompt": XIAOMAO_PROMPT,
            "status": "active",
            "is_builtin": True,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": None,
            "user_id": None,
            "name": "none（跳过正文配图）",
            "skill_name": NONE_SKILL_NAME,
            "prompt": "不生成正文配图提示词；封面仍可生成。",
            "status": "active",
            "is_builtin": True,
            "created_at": now,
            "updated_at": now,
        },
    ]


def list_illustration_characters(db: Session, user_id: int) -> list[dict]:
    custom = db.scalars(
        select(WechatMpIllustrationCharacter)
        .where(WechatMpIllustrationCharacter.user_id == user_id, WechatMpIllustrationCharacter.status == "active")
        .order_by(WechatMpIllustrationCharacter.id.desc())
    ).all()
    return builtin_characters() + [
        {
            "id": item.id,
            "user_id": item.user_id,
            "name": item.name,
            "skill_name": item.skill_name,
            "prompt": item.prompt,
            "status": item.status,
            "is_builtin": False,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in custom
    ]


def create_illustration_character(db: Session, user_id: int, *, name: str, prompt: str) -> WechatMpIllustrationCharacter:
    character = WechatMpIllustrationCharacter(
        user_id=user_id,
        name=name.strip(),
        skill_name="pending",
        prompt=prompt.strip(),
        status="active",
    )
    db.add(character)
    db.flush()
    character.skill_name = f"custom-{character.id}"
    db.commit()
    db.refresh(character)
    return character


def resolve_character_prompt(db: Session | None, user_id: int | None, skill_name: str) -> str | None:
    if skill_name == XIAOMAO_SKILL_NAME:
        return XIAOMAO_PROMPT
    if skill_name == NONE_SKILL_NAME:
        return "不生成正文配图。"
    if db is None or user_id is None or not skill_name.startswith("custom-"):
        return None
    character = db.scalar(
        select(WechatMpIllustrationCharacter).where(
            WechatMpIllustrationCharacter.user_id == user_id,
            WechatMpIllustrationCharacter.skill_name == skill_name,
            WechatMpIllustrationCharacter.status == "active",
        )
    )
    return character.prompt if character else None
