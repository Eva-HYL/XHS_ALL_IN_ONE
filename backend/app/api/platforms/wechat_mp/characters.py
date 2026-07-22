from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User
from backend.app.schemas.wechat_mp import WechatMpIllustrationCharacterCreateRequest, WechatMpIllustrationCharacterResponse
from backend.app.services.wechat_mp_character_service import create_illustration_character, list_illustration_characters


router = APIRouter(prefix="/platforms/wechat-mp/illustration-characters", tags=["wechat-mp-illustration-characters"])


@router.get("", response_model=list[WechatMpIllustrationCharacterResponse])
def list_characters(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_illustration_characters(db, current_user.id)


@router.post("", response_model=WechatMpIllustrationCharacterResponse, status_code=status.HTTP_201_CREATED)
def create_character(
    payload: WechatMpIllustrationCharacterCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = create_illustration_character(db, current_user.id, name=payload.name, prompt=payload.prompt)
    return {
        "id": character.id,
        "user_id": character.user_id,
        "name": character.name,
        "skill_name": character.skill_name,
        "prompt": character.prompt,
        "status": character.status,
        "is_builtin": False,
        "created_at": character.created_at,
        "updated_at": character.updated_at,
    }
