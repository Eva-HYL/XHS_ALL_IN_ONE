from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import Character, User
from backend.app.schemas.characters import (
    CharacterCreateRequest,
    CharacterUpdateRequest,
)
from backend.app.schemas.common import paginated

router = APIRouter(prefix="/characters", tags=["characters"])


def _serialize(char: Character) -> dict:
    return {
        "id": char.id,
        "name": char.name,
        "slug": char.slug,
        "ip_definition": char.ip_definition,
        "reference_image_asset_ids": char.reference_image_asset_ids or [],
        "created_via": char.created_via,
        "created_at": char.created_at.isoformat(),
        "updated_at": char.updated_at.isoformat(),
    }


def _get_owned(db: Session, current_user: User, character_id: int) -> Character:
    char = db.get(Character, character_id)
    if char is None or char.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    return char


@router.post("", status_code=status.HTTP_201_CREATED)
def create_character(
    payload: CharacterCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = Character(
        user_id=current_user.id,
        name=payload.name,
        slug=payload.slug,
        ip_definition=payload.ip_definition,
        reference_image_asset_ids=list(payload.reference_image_asset_ids),
        created_via=payload.created_via,
    )
    db.add(char)
    db.commit()
    db.refresh(char)
    return _serialize(char)


@router.get("")
def list_characters(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 20,
):
    # backend/app/schemas/common.paginated does in-Python slicing — pass full result.
    # Fine here: characters are personal-scale.
    stmt = select(Character).where(Character.user_id == current_user.id).order_by(Character.id.desc())
    items = db.scalars(stmt).all()
    return paginated([_serialize(c) for c in items], page=page, page_size=page_size)


@router.get("/{character_id}")
def get_character(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _serialize(_get_owned(db, current_user, character_id))


@router.patch("/{character_id}")
def update_character(
    character_id: int,
    payload: CharacterUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _get_owned(db, current_user, character_id)
    if payload.name is not None:
        char.name = payload.name
    if payload.ip_definition is not None:
        char.ip_definition = payload.ip_definition
    if payload.reference_image_asset_ids is not None:
        char.reference_image_asset_ids = list(payload.reference_image_asset_ids)
    db.commit()
    db.refresh(char)
    return _serialize(char)


@router.delete("/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_character(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    char = _get_owned(db, current_user, character_id)
    db.delete(char)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
