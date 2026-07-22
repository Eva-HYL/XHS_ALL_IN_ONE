from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User, WechatMpMaterial
from backend.app.schemas.common import paginated
from backend.app.schemas.wechat_mp import (
    WechatMpMaterialCreateRequest,
    WechatMpMaterialResponse,
    WechatMpMaterialUpdateRequest,
)


router = APIRouter(prefix="/platforms/wechat-mp/materials", tags=["wechat-mp-materials"])


def _get_owned_material(db: Session, user_id: int, material_id: int) -> WechatMpMaterial:
    material = db.get(WechatMpMaterial, material_id)
    if material is None or material.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP material not found")
    return material


@router.get("")
def list_materials(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
    material_type: str | None = None,
    q: str | None = None,
):
    query = select(WechatMpMaterial).where(
        WechatMpMaterial.user_id == current_user.id,
        WechatMpMaterial.status == "active",
    )
    if material_type:
        query = query.where(WechatMpMaterial.material_type == material_type)
    materials = db.scalars(query.order_by(WechatMpMaterial.id.desc())).all()
    if q:
        needle = q.strip().lower()
        materials = [
            item for item in materials
            if needle in item.title.lower()
            or needle in item.content.lower()
            or needle in item.notes.lower()
            or any(needle in str(tag).lower() for tag in item.tags)
        ]
    return paginated(
        [WechatMpMaterialResponse.model_validate(item).model_dump(mode="json") for item in materials],
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=WechatMpMaterialResponse, status_code=status.HTTP_201_CREATED)
def create_material(
    payload: WechatMpMaterialCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    material = WechatMpMaterial(
        user_id=current_user.id,
        title=payload.title,
        material_type=payload.material_type,
        content=payload.content,
        source_url=payload.source_url,
        tags=payload.tags,
        notes=payload.notes,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    return material


@router.patch("/{material_id}", response_model=WechatMpMaterialResponse)
def update_material(
    material_id: int,
    payload: WechatMpMaterialUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    material = _get_owned_material(db, current_user.id, material_id)
    for field in ("title", "material_type", "content", "source_url", "tags", "notes", "status"):
        value = getattr(payload, field)
        if value is not None:
            setattr(material, field, value)
    db.commit()
    db.refresh(material)
    return material


@router.delete("/{material_id}")
def delete_material(
    material_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    material = _get_owned_material(db, current_user.id, material_id)
    material.status = "deleted"
    db.commit()
    return {"id": material_id, "status": "deleted"}
