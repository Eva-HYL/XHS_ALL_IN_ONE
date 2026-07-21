from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User, WechatMpAsset
from backend.app.schemas.common import paginated
from backend.app.schemas.wechat_mp import WechatMpAssetResponse


router = APIRouter(prefix="/platforms/wechat-mp", tags=["wechat-mp-assets"])


def _get_owned_asset(db: Session, user_id: int, asset_id: int) -> WechatMpAsset:
    asset = db.get(WechatMpAsset, asset_id)
    if asset is None or asset.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat MP asset not found")
    return asset


def _delete_local_media(file_path: str) -> None:
    media_dir = (Path(get_settings().storage_dir) / "media").resolve()
    candidate = Path(file_path).resolve()
    if candidate.is_relative_to(media_dir) and candidate.is_file():
        candidate.unlink()


@router.get("/assets")
def list_assets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
):
    assets = db.scalars(select(WechatMpAsset).where(
        WechatMpAsset.user_id == current_user.id,
    ).order_by(WechatMpAsset.id.desc())).all()
    return paginated([WechatMpAssetResponse.model_validate(asset).model_dump(mode="json") for asset in assets], page=page, page_size=page_size)


@router.delete("/assets/{asset_id}")
def delete_asset(
    asset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    asset = _get_owned_asset(db, current_user.id, asset_id)
    _delete_local_media(asset.file_path)
    db.delete(asset)
    db.commit()
    return {"id": asset_id, "status": "deleted"}
