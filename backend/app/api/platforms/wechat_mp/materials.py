from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

import requests
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
FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_DOCX_RAW_CONTENT_URL = "https://open.feishu.cn/open-apis/docx/v1/documents/{token}/raw_content"
FEISHU_DOC_RAW_CONTENT_URL = "https://open.feishu.cn/open-apis/doc/v2/{token}/raw_content"


class FeishuMaterialParseError(ValueError):
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(message)
        self.status_code = status_code


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


def _parse_feishu_document(url: str) -> tuple[str, str]:
    if not re.search(r"(feishu\.cn|larksuite\.com)", url, flags=re.IGNORECASE):
        raise FeishuMaterialParseError("请填写飞书或 Lark 文档链接")
    patterns = (
        (r"/docx/([A-Za-z0-9]+)", "docx"),
        (r"/docs/([A-Za-z0-9]+)", "doc"),
        (r"/doc/([A-Za-z0-9]+)", "doc"),
    )
    for pattern, document_type in patterns:
        match = re.search(pattern, url)
        if match:
            return document_type, match.group(1)
    raise FeishuMaterialParseError("暂只支持飞书 docx/doc 文档链接")


def _feishu_credentials() -> tuple[str, str]:
    app_id = (os.getenv("FEISHU_APP_ID") or os.getenv("LARK_APP_ID") or "").strip()
    app_secret = (os.getenv("FEISHU_APP_SECRET") or os.getenv("LARK_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise FeishuMaterialParseError("未配置飞书应用凭证：请设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
    return app_id, app_secret


def _get_feishu_tenant_access_token() -> str:
    app_id, app_secret = _feishu_credentials()
    try:
        response = requests.post(
            FEISHU_TOKEN_URL,
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=20,
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise FeishuMaterialParseError("飞书 access token 获取失败，请检查网络或凭证配置", status.HTTP_502_BAD_GATEWAY) from exc
    if payload.get("code") != 0:
        raise FeishuMaterialParseError(
            f"飞书 access token 获取失败：{payload.get('msg') or payload.get('code')}",
            status.HTTP_502_BAD_GATEWAY,
        )
    token = payload.get("tenant_access_token")
    if not token:
        raise FeishuMaterialParseError("飞书 access token 返回为空", status.HTTP_502_BAD_GATEWAY)
    return token


def _fetch_feishu_raw_content(source_url: str) -> str:
    document_type, document_token = _parse_feishu_document(source_url)
    tenant_access_token = _get_feishu_tenant_access_token()
    raw_content_url = (
        FEISHU_DOCX_RAW_CONTENT_URL if document_type == "docx" else FEISHU_DOC_RAW_CONTENT_URL
    ).format(token=document_token)
    try:
        response = requests.get(
            raw_content_url,
            headers={"Authorization": f"Bearer {tenant_access_token}"},
            timeout=30,
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise FeishuMaterialParseError("飞书文档解析失败，请检查文档权限或网络", status.HTTP_502_BAD_GATEWAY) from exc
    if payload.get("code") != 0:
        raise FeishuMaterialParseError(
            f"飞书文档解析失败：{payload.get('msg') or payload.get('code')}",
            status.HTTP_502_BAD_GATEWAY,
        )
    content = payload.get("data", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise FeishuMaterialParseError("飞书文档内容为空或无法读取")
    return content.strip()


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


@router.post("/{material_id}/parse-feishu", response_model=WechatMpMaterialResponse)
def parse_feishu_material(
    material_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    material = _get_owned_material(db, current_user.id, material_id)
    if not material.source_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先填写飞书文档链接")
    try:
        material.content = _fetch_feishu_raw_content(material.source_url)
    except FeishuMaterialParseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    material.material_type = "link"
    tags = list(material.tags or [])
    if "飞书" not in tags:
        tags.append("飞书")
    material.tags = tags
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
