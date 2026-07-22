from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
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

ALLOWED_MATERIAL_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".pdf",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
}
MAX_MATERIAL_FILE_SIZE = 50 * 1024 * 1024


def _materials_dir() -> Path:
    return Path(get_settings().storage_dir) / "materials"


def _material_file_prefix(user_id: int) -> str:
    return f"wechat-mp-material-u{user_id}-"


def _get_owned_material(db: Session, user_id: int, material_id: int) -> WechatMpMaterial:
    material = db.get(WechatMpMaterial, material_id)
    if material is None or material.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP material not found")
    return material


def _delete_local_material_file(material: WechatMpMaterial) -> None:
    if not material.file_path:
        return
    materials_dir = _materials_dir().resolve()
    candidate = Path(material.file_path).resolve()
    if candidate.is_relative_to(materials_dir) and candidate.is_file():
        candidate.unlink()


@router.get("/files/{file_name}")
def download_material_file(
    file_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if Path(file_name).name != file_name or ".." in file_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP material file not found")
    if not file_name.startswith(_material_file_prefix(current_user.id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP material file not found")
    material = db.scalar(select(WechatMpMaterial).where(
        WechatMpMaterial.user_id == current_user.id,
        WechatMpMaterial.file_name == file_name,
        WechatMpMaterial.status == "active",
    ))
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP material file not found")
    file_path = _materials_dir() / file_name
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP material file not found")
    return FileResponse(
        file_path,
        filename=material.original_file_name or file_name,
        media_type=material.mime_type or "application/octet-stream",
    )


@router.post("/upload", response_model=WechatMpMaterialResponse, status_code=status.HTTP_201_CREATED)
async def upload_material_file(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件名不能为空")
    original_file_name = Path(file.filename).name
    ext = Path(original_file_name).suffix.lower()
    if ext not in ALLOWED_MATERIAL_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"不支持的资料文件格式: {ext}")
    content = await file.read()
    if len(content) > MAX_MATERIAL_FILE_SIZE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料文件大小超过 50MB 限制")

    file_name = f"{_material_file_prefix(current_user.id)}{uuid4().hex}{ext}"
    materials_dir = _materials_dir()
    materials_dir.mkdir(parents=True, exist_ok=True)
    file_path = materials_dir / file_name
    file_path.write_bytes(content)
    material = WechatMpMaterial(
        user_id=current_user.id,
        title=Path(original_file_name).stem or original_file_name,
        material_type="file",
        original_file_name=original_file_name,
        file_name=file_name,
        file_path=str(file_path.resolve()),
        download_url=f"/api/platforms/wechat-mp/materials/files/{file_name}",
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
        tags=["文件"],
        notes="上传文件资料",
    )
    db.add(material)
    db.commit()
    db.refresh(material)
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
        file_name=payload.file_name,
        original_file_name=payload.original_file_name,
        file_path=payload.file_path,
        download_url=payload.download_url,
        file_size=payload.file_size,
        mime_type=payload.mime_type,
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
    for field in (
        "title", "material_type", "content", "source_url", "file_name", "original_file_name",
        "file_path", "download_url", "file_size", "mime_type", "tags", "notes", "status",
    ):
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
    _delete_local_material_file(material)
    material.status = "deleted"
    db.commit()
    return {"id": material_id, "status": "deleted"}
