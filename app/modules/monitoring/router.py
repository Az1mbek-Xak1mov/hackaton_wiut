from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.scopes import Scope
from app.modules.auth.deps import require_scope
from app.modules.jobs.schemas import JobOut
from app.modules.monitoring.service import _run_out, latest_run, portfolio_summary, start_run

router = APIRouter(prefix="/api/v1", tags=["monitoring"])


class RunCreate(BaseModel):
    as_of: date | None = None


@router.post("/monitoring/runs", status_code=202)
def create_run(data: RunCreate | None = None, db: Session = Depends(get_db),
               actor=Depends(require_scope(Scope.MONITORING_RUN))):
    run, job = start_run(db, actor, (data.as_of if data else None))
    return {"run": _run_out(run), "job": JobOut.model_validate(job)}


@router.get("/monitoring/runs/latest")
def get_latest_run(db: Session = Depends(get_db), _=Depends(require_scope(Scope.MONITORING_READ))):
    return {"run": _run_out(latest_run(db))}


@router.get("/portfolio/summary")
def get_portfolio_summary(db: Session = Depends(get_db), _=Depends(require_scope(Scope.MONITORING_READ))):
    return portfolio_summary(db)
