from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.scopes import Scope
from app.modules.applications.review import _narrative, build_review
from app.modules.applications.schemas import ApplicationCreate, DecisionCreate
from app.modules.applications.service import ApplicationService
from app.modules.auth.deps import require_scope
from app.modules.jobs.schemas import JobOut

router = APIRouter(prefix="/api/v1", tags=["applications"])
read = require_scope(Scope.APPLICATION_READ)
write = require_scope(Scope.APPLICATION_WRITE)


@router.get("/applications")
def list_applications(db: Session = Depends(get_db), _=Depends(read)):
    return {"items": ApplicationService(db).list_items()}


@router.post("/applications", status_code=201)
def create_application(data: ApplicationCreate, db: Session = Depends(get_db), actor=Depends(write)):
    app = ApplicationService(db).create_application(data.model_dump(), actor)
    return {"uuid": str(app.uuid), "number": app.number, "status": app.status}


@router.post("/applications/{ref}/documents", status_code=201)
def attach_document(ref: str, file: UploadFile = File(...), db: Session = Depends(get_db), actor=Depends(write)):
    s = ApplicationService(db)
    doc, job = s.attach_upload(s.app_or_404(ref), file.file.read(), file.filename or "upload", actor)
    return {"uuid": str(doc.uuid), "job": JobOut.model_validate(job)}


@router.post("/applications/{ref}/analyse", status_code=202, response_model=JobOut)
def analyse_application(ref: str, db: Session = Depends(get_db), actor=Depends(write)):
    s = ApplicationService(db)
    return s.analyse(s.app_or_404(ref), actor)


@router.get("/applications/{ref}/review")
def application_review(ref: str, db: Session = Depends(get_db), _=Depends(read)):
    return build_review(db, ApplicationService(db).app_or_404(ref))


@router.get("/applications/{ref}/narrative")
def application_narrative(ref: str, db: Session = Depends(get_db), _=Depends(read)):
    app = ApplicationService(db).app_or_404(ref)
    return _narrative(db, app_id=app.id)


@router.post("/applications/{ref}/narrative/regenerate", status_code=202, response_model=JobOut)
def regenerate_narrative(ref: str, db: Session = Depends(get_db), actor=Depends(write)):
    s = ApplicationService(db)
    return s.regenerate_narrative(s.app_or_404(ref), actor)


@router.post("/applications/{ref}/decision", status_code=201)
def record_decision(ref: str, data: DecisionCreate, db: Session = Depends(get_db),
                    actor=Depends(require_scope(Scope.DECISION_WRITE))):
    s = ApplicationService(db)
    dec = s.record_decision(s.app_or_404(ref), data.model_dump(), actor)
    return {"uuid": str(dec.uuid), "outcome": dec.outcome, "created_at": dec.created_at.isoformat()}
