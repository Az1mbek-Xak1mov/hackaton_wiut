import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.modules.settings.service import llm_configured, llm_enabled

router = APIRouter(prefix="/api/v1", tags=["system"])

_STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.get("/version")
def version(db: Session = Depends(get_db)):
    try:
        enabled = llm_enabled(db)
    except Exception:  # DB not migrated yet: still answer
        enabled = False
    from app.modules.llm.provider import status as llm_status
    try:
        st = llm_status(db)
    except Exception:
        st = llm_status(None)
    return {"git_sha": settings.GIT_SHA, "built_at": settings.BUILT_AT,
            "deployed_at": settings.DEPLOYED_AT or _STARTED_AT,
            "llm_provider": settings.LLM_PROVIDER, "llm_enabled": enabled,
            "llm_configured": llm_configured(), "llm_status": st["code"], "llm_status_text": st["text"],
            "demo_login": settings.DEMO_LOGIN_ENABLED}


def latest_eval_result() -> dict:
    root = Path(settings.EVAL_RESULTS_DIR)
    files = sorted(p for p in root.glob("*.json") if p.is_file()) if root.is_dir() else []
    if not files:
        return {"status": "not_measured"}
    latest = files[-1]
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "unreadable", "file": latest.name, "error": exc.__class__.__name__}
    if isinstance(data, dict):
        data.setdefault("_file", latest.name)
    return data


@router.get("/metrics/eval")
def metrics_eval():
    return latest_eval_result()
