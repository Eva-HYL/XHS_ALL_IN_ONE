from __future__ import annotations

import base64
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import requests
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models import WechatMpCharacterView, WechatMpIllustrationCharacter
from backend.app.services.illustration_size_service import normalize_illustration_size


XIAOMAO_SKILL_NAME = "xiaomao-illustrations"
XIAOMAO_CHARACTER_NAME = "小猫生图"
NONE_SKILL_NAME = "none"
CHARACTER_MENTION_RE = re.compile(r"(?m)^[ \t]*主角[：:][ \t]*@([^\s@,，。；;：:（）()]+)[ \t]*$")
CHARACTER_MENTION_DIRECTIVE_RE = re.compile(r"主角[：:][ \t]*@([^\s@,，。；;：:（）()]+)")
VIEW_ORDER = ("front", "back", "left", "right")
MAX_CHARACTER_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_CHARACTER_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
XIAOMAO_PROMPT = (
    "白色背景，横向画幅，轻微抖动的手绘线稿；"
    "主角必须是一只胖胖慵懒、半推半就但会把活干完的玳瑁猫，"
    "身体以黑白色块为主，背、头、尾点缀少量橙斑，半闭眼、冷淡表情；"
    "小猫自然趴卧并辅助表达画面核心概念，不穿衣、不画成可爱吉祥物；"
    "画面留白充足，一图一个核心结构，不使用写实摄影、3D 渲染、复杂背景或大段文字；"
    "不得渲染标题、比例、尺寸、提示词、说明文字、水印、签名或图中文字。"
)


def _character_dir(user_id: int) -> Path:
    path = Path(get_settings().storage_dir) / "character-images" / f"u{user_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _empty_view(view: str) -> dict:
    return {"id": None, "view": view, "prompt": "", "public_url": "", "model_name": "", "status": "draft"}


def _serialize_character(character: WechatMpIllustrationCharacter) -> dict:
    records = {item.view: item for item in character.views}
    views = [records[view] if view in records else _empty_view(view) for view in VIEW_ORDER]
    available = all(
        (item["status"] == "confirmed" and item["public_url"]) if isinstance(item, dict)
        else (item.status == "confirmed" and item.public_url)
        for item in views
    )
    return {
        "id": character.id, "user_id": character.user_id, "name": character.name,
        "skill_name": character.skill_name, "prompt": character.prompt, "status": "confirmed" if available else "draft",
        "anchor_version": character.anchor_version, "is_available": available,
        "views": views, "is_builtin": character.skill_name == XIAOMAO_SKILL_NAME,
        "created_at": character.created_at, "updated_at": character.updated_at,
    }


def format_character_mention(character: WechatMpIllustrationCharacter) -> str:
    return f"主角：@{character.name}"


def format_character_prompt(character: WechatMpIllustrationCharacter, scene_prompt: str) -> str:
    _, cleaned = parse_character_mention(scene_prompt)
    cleaned = cleaned.strip()
    if cleaned and not cleaned.startswith("具体画面："):
        cleaned = f"具体画面：{cleaned}"
    return "\n".join(part for part in (format_character_mention(character), cleaned) if part)


def canonicalize_character_prompt(
    character: WechatMpIllustrationCharacter | None,
    scene_prompt: str,
    *,
    include_character: bool,
) -> str:
    """Keep stored prompts in reference form, never with a full character contract."""
    cleaned = scene_prompt.replace(character.prompt, "") if character is not None else scene_prompt
    cleaned = CHARACTER_MENTION_DIRECTIVE_RE.sub("", cleaned)
    cleaned = "\n".join(line.strip() for line in cleaned.splitlines() if line.strip())
    if include_character and character is not None:
        return format_character_prompt(character, cleaned)
    return cleaned.strip()


def parse_character_mention(text: str) -> tuple[str | None, str]:
    directives = CHARACTER_MENTION_DIRECTIVE_RE.findall(text)
    names = CHARACTER_MENTION_RE.findall(text)
    if len(directives) > 1:
        raise ValueError("Each prompt supports one primary @character mention")
    if directives and len(names) != 1:
        raise ValueError("Character mention must be on its own line")
    name = names[0] if names else None
    cleaned = CHARACTER_MENTION_RE.sub("", text).strip()
    return name, cleaned


def ensure_builtin_character(db: Session, user_id: int) -> WechatMpIllustrationCharacter:
    character = db.scalar(select(WechatMpIllustrationCharacter).where(
        WechatMpIllustrationCharacter.user_id == user_id,
        WechatMpIllustrationCharacter.skill_name == XIAOMAO_SKILL_NAME,
    ))
    if character is None:
        character = WechatMpIllustrationCharacter(
            user_id=user_id, name=XIAOMAO_CHARACTER_NAME, skill_name=XIAOMAO_SKILL_NAME,
            prompt=XIAOMAO_PROMPT, status="draft", anchor_version=1,
        )
        db.add(character)
        db.commit()
    elif character.name != XIAOMAO_CHARACTER_NAME:
        character.name = XIAOMAO_CHARACTER_NAME
        db.commit()
    return character


def list_illustration_characters(db: Session, user_id: int) -> list[dict]:
    ensure_builtin_character(db, user_id)
    characters = db.scalars(
        select(WechatMpIllustrationCharacter)
        .where(
            WechatMpIllustrationCharacter.user_id == user_id,
            WechatMpIllustrationCharacter.archived_at.is_(None),
        )
        .order_by(WechatMpIllustrationCharacter.skill_name != XIAOMAO_SKILL_NAME, WechatMpIllustrationCharacter.id.desc())
    ).unique().all()
    builtin = [item for item in characters if item.skill_name == XIAOMAO_SKILL_NAME]
    custom = [item for item in characters if item.skill_name != XIAOMAO_SKILL_NAME]
    result = [_serialize_character(item) for item in builtin]
    result.append({"id": None, "user_id": None, "name": "none（跳过正文配图）", "skill_name": NONE_SKILL_NAME,
                   "prompt": "不生成正文配图提示词；封面仍可生成。", "status": "confirmed", "anchor_version": 1,
                   "is_available": True, "views": [], "is_builtin": True})
    result.extend(_serialize_character(item) for item in custom)
    return result


def create_illustration_character(db: Session, user_id: int, *, name: str, prompt: str) -> WechatMpIllustrationCharacter:
    character = WechatMpIllustrationCharacter(
        user_id=user_id, name=name.strip(), skill_name="pending", prompt=prompt.strip(), status="draft", anchor_version=1,
    )
    db.add(character)
    db.flush()
    character.skill_name = f"custom-{character.id}"
    db.commit()
    db.refresh(character)
    return character


def get_owned_character(db: Session, user_id: int, character_id: int) -> WechatMpIllustrationCharacter:
    character = db.scalar(select(WechatMpIllustrationCharacter).where(
        WechatMpIllustrationCharacter.id == character_id,
        WechatMpIllustrationCharacter.user_id == user_id,
    ))
    if character is None:
        raise LookupError("WeChat MP character not found")
    return character


def archive_illustration_character(db: Session, user_id: int, character_id: int) -> None:
    character = db.scalar(select(WechatMpIllustrationCharacter).where(
        WechatMpIllustrationCharacter.id == character_id,
        WechatMpIllustrationCharacter.user_id == user_id,
        WechatMpIllustrationCharacter.archived_at.is_(None),
    ))
    if character is None:
        raise LookupError("WeChat MP character not found")
    if character.skill_name == XIAOMAO_SKILL_NAME:
        raise ValueError("Built-in WeChat MP character cannot be deleted")
    character.archived_at = datetime.utcnow()
    db.commit()


def _get_or_create_view(db: Session, character: WechatMpIllustrationCharacter, view: str) -> WechatMpCharacterView:
    if view not in VIEW_ORDER:
        raise ValueError("Unsupported character view")
    record = db.scalar(select(WechatMpCharacterView).where(
        WechatMpCharacterView.character_id == character.id, WechatMpCharacterView.view == view,
    ))
    if record is None:
        record = WechatMpCharacterView(character_id=character.id, user_id=character.user_id, view=view)
        db.add(record)
    return record


def _refresh_character_status(db: Session, character: WechatMpIllustrationCharacter) -> None:
    records = {item.view: item for item in db.scalars(select(WechatMpCharacterView).where(
        WechatMpCharacterView.character_id == character.id
    )).all()}
    character.status = "confirmed" if all(
        records.get(view) is not None and records[view].status == "confirmed" and records[view].public_url
        for view in VIEW_ORDER
    ) else "draft"


def _replace_view(character: WechatMpIllustrationCharacter, record: WechatMpCharacterView, *, prompt: str, file_path: str, public_url: str, model_name: str) -> None:
    record.prompt = prompt
    record.file_path = file_path
    record.public_url = public_url
    record.model_name = model_name
    record.status = "draft"
    character.status = "draft"
    character.anchor_version += 1


async def upload_character_view(db: Session, *, character: WechatMpIllustrationCharacter, view: str, upload: UploadFile) -> WechatMpCharacterView:
    if upload.content_type not in ALLOWED_CHARACTER_IMAGE_TYPES:
        raise ValueError("Character view must be JPEG, PNG, or WebP")
    content = await upload.read()
    if not content or len(content) > MAX_CHARACTER_IMAGE_BYTES:
        raise ValueError("Character view must be no larger than 10 MiB")
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[upload.content_type]
    filename = f"{uuid4().hex}{suffix}"
    path = _character_dir(character.user_id) / filename
    path.write_bytes(content)
    record = _get_or_create_view(db, character, view)
    _replace_view(character, record, prompt=character.prompt, file_path=str(path),
                  public_url=f"/api/platforms/wechat-mp/illustration-characters/files/{filename}", model_name="uploaded")
    db.commit()
    db.refresh(record)
    return record


def _view_prompt(character: WechatMpIllustrationCharacter, view: str) -> str:
    return f"{character.prompt}\nSame character, {view} view, full body, neutral pose. Do not render any text, labels, watermark, or view name."


def generate_character_view(db: Session, *, character: WechatMpIllustrationCharacter, view: str, model_name: str, base_url: str, api_key: str) -> WechatMpCharacterView:
    from backend.app.services.wechat_mp_image_service import _call_image_model

    if view not in VIEW_ORDER:
        raise ValueError("Unsupported character view")
    confirmed_urls = [item.public_url for item in character.views if item.status == "confirmed" and item.public_url]
    size = normalize_illustration_size(model_name, "1:1")
    result = _call_image_model(prompt=_view_prompt(character, view), model_name=model_name, size=size, base_url=base_url, api_key=api_key, reference_images=confirmed_urls or None)
    image_ref = result["image_ref"]
    content = requests.get(image_ref, timeout=30).content if image_ref.startswith(("http://", "https://")) else base64.b64decode(image_ref)
    filename = f"{uuid4().hex}.png"
    path = _character_dir(character.user_id) / filename
    path.write_bytes(content)
    record = _get_or_create_view(db, character, view)
    _replace_view(character, record, prompt=_view_prompt(character, view), file_path=str(path),
                  public_url=f"/api/platforms/wechat-mp/illustration-characters/files/{filename}", model_name=model_name)
    db.commit()
    db.refresh(record)
    return record


def confirm_character_view(db: Session, *, character: WechatMpIllustrationCharacter, view: str) -> WechatMpCharacterView:
    record = _get_or_create_view(db, character, view)
    if not record.public_url:
        raise ValueError("Character view must be generated or uploaded before confirmation")
    record.status = "confirmed"
    _refresh_character_status(db, character)
    db.commit()
    db.refresh(record)
    return record


def resolve_character_prompt(db: Session | None, user_id: int | None, skill_name: str) -> str | None:
    if skill_name == NONE_SKILL_NAME:
        return "不生成正文配图。"
    if db is None or user_id is None:
        return None
    character = db.scalar(select(WechatMpIllustrationCharacter).where(
        WechatMpIllustrationCharacter.user_id == user_id, WechatMpIllustrationCharacter.skill_name == skill_name,
    ))
    return character.prompt if character else None


def resolve_character_by_skill(
    db: Session,
    *,
    user_id: int,
    skill_name: str,
) -> WechatMpIllustrationCharacter | None:
    if skill_name == NONE_SKILL_NAME:
        return None
    if skill_name == XIAOMAO_SKILL_NAME:
        return ensure_builtin_character(db, user_id)
    return db.scalar(select(WechatMpIllustrationCharacter).where(
        WechatMpIllustrationCharacter.user_id == user_id,
        WechatMpIllustrationCharacter.skill_name == skill_name,
        WechatMpIllustrationCharacter.archived_at.is_(None),
    ))


def resolve_confirmed_character_anchor(db: Session, *, user_id: int, character_id: int | None = None, skill_name: str | None = None) -> tuple[WechatMpIllustrationCharacter, list[str]] | None:
    if skill_name == NONE_SKILL_NAME:
        return None
    character = get_owned_character(db, user_id, character_id) if character_id else db.scalar(select(WechatMpIllustrationCharacter).where(
        WechatMpIllustrationCharacter.user_id == user_id, WechatMpIllustrationCharacter.skill_name == skill_name,
    ))
    if character is None:
        raise ValueError("Selected character is not available")
    records = {item.view: item for item in character.views}
    urls = [records[view].public_url for view in VIEW_ORDER if records.get(view) and records[view].status == "confirmed" and records[view].public_url]
    if len(urls) != 4:
        raise ValueError("Selected character needs four confirmed views before image generation")
    return character, urls


def resolve_prompt_character(
    db: Session,
    *,
    user_id: int,
    default_skill_name: str,
    text: str,
    default_character_id: int | None = None,
) -> tuple[WechatMpIllustrationCharacter | None, str]:
    name, cleaned = parse_character_mention(text)
    if name is None:
        anchor = resolve_confirmed_character_anchor(
            db,
            user_id=user_id,
            character_id=default_character_id,
            skill_name=None if default_character_id else default_skill_name,
        )
        return (anchor[0] if anchor else None), cleaned
    if default_character_id is not None:
        default_character = get_owned_character(db, user_id, default_character_id)
        if default_character.archived_at is not None:
            raise ValueError("Selected character is not available")
        if default_character.name == name:
            resolve_confirmed_character_anchor(db, user_id=user_id, character_id=default_character.id)
            return default_character, cleaned
    matches = db.scalars(select(WechatMpIllustrationCharacter).where(
        WechatMpIllustrationCharacter.user_id == user_id,
        WechatMpIllustrationCharacter.name == name,
        WechatMpIllustrationCharacter.archived_at.is_(None),
    )).all()
    if not matches:
        raise ValueError("Mentioned character was not found")
    if len(matches) > 1:
        raise ValueError("Ambiguous character mention; select a character from the confirmed character picker")
    character = matches[0]
    resolve_confirmed_character_anchor(db, user_id=user_id, character_id=character.id)
    return character, cleaned
