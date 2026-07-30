from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User
from backend.app.schemas.wechat_mp import (
    WechatMpCharacterViewResponse,
    WechatMpIllustrationCharacterCreateRequest,
    WechatMpIllustrationCharacterResponse,
)
from backend.app.services.wechat_mp_character_service import (
    confirm_character_view,
    create_illustration_character,
    generate_character_view,
    get_owned_character,
    list_illustration_characters,
    upload_character_view,
)
from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model


router = APIRouter(prefix="/platforms/wechat-mp/illustration-characters", tags=["wechat-mp-illustration-characters"])


def _not_found(exc: LookupError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("", response_model=list[WechatMpIllustrationCharacterResponse])
def list_characters(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_illustration_characters(db, current_user.id)


@router.post("", response_model=WechatMpIllustrationCharacterResponse, status_code=status.HTTP_201_CREATED)
def create_character(payload: WechatMpIllustrationCharacterCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    character = create_illustration_character(db, current_user.id, name=payload.name, prompt=payload.prompt)
    return next(item for item in list_illustration_characters(db, current_user.id) if item["id"] == character.id)


@router.post("/{character_id}/views/{view}/upload", response_model=WechatMpCharacterViewResponse, status_code=status.HTTP_201_CREATED)
async def upload_view(character_id: int, view: str, file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        character = get_owned_character(db, current_user.id, character_id)
        return await upload_character_view(db, character=character, view=view, upload=file)
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{character_id}/views/{view}/generate", response_model=WechatMpCharacterViewResponse, status_code=status.HTTP_201_CREATED)
def generate_view(character_id: int, view: str, image_model: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        character = get_owned_character(db, current_user.id, character_id)
        model = resolve_wechat_mp_model(db=db, user_id=current_user.id, model_type="image", requested_model=image_model)
        return generate_character_view(db, character=character, view=view, model_name=model.model_name, base_url=model.base_url, api_key=model.api_key)
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/{character_id}/views/{view}/confirm", response_model=WechatMpCharacterViewResponse)
def confirm_view(character_id: int, view: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        character = get_owned_character(db, current_user.id, character_id)
        return confirm_character_view(db, character=character, view=view)
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/files/{file_name}")
def get_character_file(file_name: str, current_user: User = Depends(get_current_user)):
    if Path(file_name).name != file_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character image not found")
    path = Path(__import__("backend.app.core.config", fromlist=["get_settings"]).get_settings().storage_dir) / "character-images" / f"u{current_user.id}" / file_name
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character image not found")
    return FileResponse(path)
