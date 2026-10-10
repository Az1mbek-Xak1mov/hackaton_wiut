from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.scopes import Scope
from app.modules.auth.deps import get_current_user, require_scope
from app.modules.settings.schemas import LlmSettings, LlmSettingsUpdate
from app.modules.settings.service import SettingsService

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("/llm", response_model=LlmSettings)
def get_llm(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return SettingsService(db).llm_status()


@router.put("/llm", response_model=LlmSettings)
def put_llm(data: LlmSettingsUpdate, db: Session = Depends(get_db), actor=Depends(require_scope(Scope.SETTINGS_WRITE))):
    return SettingsService(db).set_llm_enabled(data.enabled, actor)
