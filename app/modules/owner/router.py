from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.scopes import Scope
from app.modules.auth.deps import require_scope
from app.modules.borrowers.service import BorrowerService
from app.modules.documents.models import Document
from app.modules.documents.service import DocumentService
from app.modules.jobs.schemas import JobOut

router = APIRouter(prefix="/api/v1/owner", tags=["owner"])


@router.get("/files")
def owner_files(db: Session = Depends(get_db), user=Depends(require_scope(Scope.OWNER_FILES))):
    b = BorrowerService(db).owner_borrower(user)
    docs = db.scalars(select(Document).where(Document.borrower_id == b.id).order_by(Document.id.desc())).all()
    s = DocumentService(db)
    return {"business": {"uuid": str(b.uuid), "name": b.name, "industry": b.industry, "region": b.region},
            "items": [s.dump(d) for d in docs]}


@router.post("/files", status_code=201)
def owner_upload(file: UploadFile = File(...), db: Session = Depends(get_db),
                 user=Depends(require_scope(Scope.DOCUMENT_WRITE))):
    b = BorrowerService(db).owner_borrower(user)
    doc, job = DocumentService(db).upload(file.file.read(), file.filename or "upload", owner_kind="owner",
                                          borrower_id=b.id, actor=user)
    return {"uuid": str(doc.uuid), "job": JobOut.model_validate(job)}
