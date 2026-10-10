from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.scopes import Scope
from app.modules.applications.service import ApplicationService
from app.modules.auth.deps import require_scope
from app.modules.auth.schemas import UserOut
from app.modules.borrowers.service import BorrowerService
from app.modules.documents.models import Document
from app.modules.documents.service import DocumentService
from app.modules.jobs.schemas import JobOut

router = APIRouter(prefix="/api/v1/owner", tags=["owner"])


class OwnerApplicationCreate(BaseModel):
    requested_amount_mln: float = Field(gt=0, le=1_000_000)
    term_months: int = Field(ge=1, le=360)
    purpose: str = Field(default="", max_length=255)
    document_uuids: list[UUID] | None = None


def _business(b) -> dict:
    return {"uuid": str(b.uuid), "name": b.name, "stir": b.stir, "industry": b.industry, "region": b.region}


@router.get("/me")
def owner_me(db: Session = Depends(get_db), user=Depends(require_scope(Scope.OWNER_FILES))):
    b = BorrowerService(db).owner_borrower(user)
    return {"user": UserOut.model_validate(user), "business": _business(b)}


@router.post("/applications", status_code=201)
def owner_apply(data: OwnerApplicationCreate, db: Session = Depends(get_db),
                user=Depends(require_scope(Scope.OWNER_FILES))):
    app, job = ApplicationService(db).create_owner_application(user, data.model_dump())
    return {"uuid": str(app.uuid), "number": app.number, "status": app.status, "job": JobOut.model_validate(job)}


@router.get("/applications")
def owner_applications(db: Session = Depends(get_db), user=Depends(require_scope(Scope.OWNER_FILES))):
    return {"items": ApplicationService(db).owner_items(user)}


@router.get("/files")
def owner_files(db: Session = Depends(get_db), user=Depends(require_scope(Scope.OWNER_FILES))):
    b = BorrowerService(db).owner_borrower(user)
    docs = db.scalars(select(Document).where(Document.borrower_id == b.id).order_by(Document.id.desc())).all()
    s = DocumentService(db)
    return {"business": _business(b), "items": [s.dump(d) for d in docs]}


@router.post("/files", status_code=201)
def owner_upload(file: UploadFile = File(...), db: Session = Depends(get_db),
                 user=Depends(require_scope(Scope.OWNER_FILES))):
    b = BorrowerService(db).owner_borrower(user)
    doc, job = DocumentService(db).upload(file.file.read(), file.filename or "upload", owner_kind="owner",
                                          borrower_id=b.id, actor=user)
    return {"uuid": str(doc.uuid), "job": JobOut.model_validate(job)}
