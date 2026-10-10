from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.exceptions import NotFoundError
from app.core.scopes import Scope
from app.modules.applications.models import Application
from app.modules.applications.review import _finding_out
from app.modules.applications.schemas import FindingStateUpdate
from app.modules.applications.service import ApplicationService
from app.modules.audit import service as audit
from app.modules.auth.deps import require_scope
from app.modules.reconcile.models import Finding

router = APIRouter(prefix="/api/v1", tags=["findings"])


@router.get("/applications/{ref}/findings")
def application_findings(ref: str, db: Session = Depends(get_db), _=Depends(require_scope(Scope.APPLICATION_READ))):
    app = ApplicationService(db).app_or_404(ref)
    rows = db.scalars(select(Finding).where(Finding.application_id == app.id).order_by(Finding.id)).all()
    return {"items": [_finding_out(f) for f in rows]}


@router.patch("/findings/{finding_uuid}")
def update_finding(finding_uuid: UUID, data: FindingStateUpdate, db: Session = Depends(get_db),
                   actor=Depends(require_scope(Scope.APPLICATION_WRITE))):
    """Officer resolves or dismisses a finding with a note (H2); audited."""
    f = db.scalars(select(Finding).where(Finding.uuid == finding_uuid)).first()
    if f is None:
        raise NotFoundError("finding")
    before = {"state": f.state, "note": f.state_note}
    f.state, f.state_note = data.state, data.note
    app_uuid = None
    if f.application_id:
        app = db.get(Application, f.application_id)
        app_uuid = str(app.uuid) if app else None
    audit.record(db, actor, "update", "finding", f.uuid, before=before,
                 after={"state": f.state, "note": f.state_note, "rule_id": f.rule_id, "application_uuid": app_uuid})
    db.commit()
    return _finding_out(f)
