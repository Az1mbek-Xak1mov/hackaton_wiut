from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.audit import service as audit
from app.modules.settings.models import AppSetting

LLM_KEY = "llm_enabled"


def get_value(db: Session, key: str, default: dict | None = None) -> dict:
    row = db.scalars(select(AppSetting).where(AppSetting.key == key)).first()
    return dict(row.value) if row else dict(default or {})


def llm_enabled(db: Session) -> bool:
    """LLM is used only if the runtime switch is on AND a provider is configured."""
    if settings.LLM_PROVIDER == "none":
        return False
    return bool(get_value(db, LLM_KEY, {"enabled": True}).get("enabled", True))


def llm_configured() -> bool:
    from app.modules.llm.provider import configured
    return configured()


class SettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def llm_status(self) -> dict:
        from app.modules.llm.provider import status
        st = status(self.db)
        return {"enabled": llm_enabled(self.db), "provider": settings.LLM_PROVIDER, "model": settings.LLM_MODEL,
                "configured": llm_configured(), "status": st["code"], "status_text": st["text"]}

    def set_llm_enabled(self, enabled: bool, actor) -> dict:
        row = self.db.scalars(select(AppSetting).where(AppSetting.key == LLM_KEY)).first()
        before = dict(row.value) if row else {"enabled": True}
        if row is None:
            row = AppSetting(key=LLM_KEY, value={"enabled": enabled})
            self.db.add(row)
        else:
            row.value = {"enabled": enabled}
        self.db.flush()
        audit.record(self.db, actor, "update", "setting", row.uuid, before=before, after={"enabled": enabled})
        if bool(before.get("enabled", True)) != enabled:
            self._regenerate_narratives()
        self.db.commit()
        return self.llm_status()

    def _regenerate_narratives(self) -> None:
        """The switch shows its effect: every analysed application gets a new narrative (LLM or template)."""
        from app.modules.applications.models import Application
        from app.modules.applications.service import enqueue_analysis
        for app in self.db.scalars(select(Application).where(Application.analysed_at.is_not(None),
                                                         Application.is_public.is_(False))).all():
            enqueue_analysis(self.db, app, kind="narrative")
