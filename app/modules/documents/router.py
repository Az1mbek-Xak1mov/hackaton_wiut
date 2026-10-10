from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.exceptions import NotFoundError
from app.core.scopes import Scope
from app.modules.auth.deps import get_optional_user, require_scope
from app.modules.borrowers.models import Borrower
from app.modules.documents import storage
from app.modules.documents.service import DocumentService
from app.modules.extraction.models import Fact
from app.modules.extraction.service import FactSerializer
from app.modules.jobs.schemas import JobOut

router = APIRouter(prefix="/api/v1", tags=["documents"])


@router.post("/documents", status_code=201)
def upload_document(file: UploadFile = File(...), borrower_uuid: UUID | None = Form(default=None),
                    db: Session = Depends(get_db), actor=Depends(require_scope(Scope.DOCUMENT_WRITE))):
    borrower_id = None
    if borrower_uuid is not None:
        b = db.scalars(select(Borrower).where(Borrower.uuid == borrower_uuid)).first()
        if b is None:
            raise NotFoundError("borrower")
        borrower_id = b.id
    doc, job = DocumentService(db).upload(file.file.read(), file.filename or "upload", owner_kind="bank",
                                          borrower_id=borrower_id, actor=actor)
    return {"uuid": str(doc.uuid), "job": JobOut.model_validate(job)}


@router.get("/documents/{doc_uuid}")
def get_document(doc_uuid: UUID, request: Request, db: Session = Depends(get_db), user=Depends(get_optional_user)):
    s = DocumentService(db)
    doc = s.doc_or_404(doc_uuid)
    s.ensure_access(request, user, doc)
    return s.dump(doc)


@router.get("/documents/{doc_uuid}/pages/{n}.png")
def page_image(doc_uuid: UUID, n: int, request: Request, db: Session = Depends(get_db),
               user=Depends(get_optional_user)):
    s = DocumentService(db)
    doc = s.doc_or_404(doc_uuid)
    s.ensure_access(request, user, doc)
    path = storage.abs_path(s.page_or_404(doc, n).image_path)
    if not path.is_file():
        raise NotFoundError("page")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/documents/{doc_uuid}/original")
def original(doc_uuid: UUID, request: Request, db: Session = Depends(get_db), user=Depends(get_optional_user)):
    s = DocumentService(db)
    doc = s.doc_or_404(doc_uuid)
    s.ensure_access(request, user, doc)
    path = storage.abs_path(doc.storage_path)
    if not path.is_file():
        raise NotFoundError("file")
    return FileResponse(path, media_type=doc.mime, filename=doc.filename)


@router.get("/documents/{doc_uuid}/facts")
def document_facts(doc_uuid: UUID, request: Request, db: Session = Depends(get_db), user=Depends(get_optional_user)):
    s = DocumentService(db)
    doc = s.doc_or_404(doc_uuid)
    s.ensure_access(request, user, doc)
    facts = db.scalars(select(Fact).where(Fact.document_id == doc.id).order_by(Fact.id)).all()
    return {"facts": FactSerializer(db).many(facts)}
