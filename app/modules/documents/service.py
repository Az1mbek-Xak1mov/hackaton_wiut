from datetime import timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppException, ForbiddenError, NotFoundError
from app.core.scopes import PORTFOLIO_ROLES, Scope
from app.core.timeutil import utcnow
from app.modules.audit import service as audit
from app.modules.auth.deps import has_scope
from app.modules.borrowers.models import Borrower
from app.modules.documents import storage
from app.modules.documents.models import Document, Page
from app.modules.jobs.models import Job
from app.modules.jobs.service import PUBLIC_PRIORITY, JobService

DOC_FIELDS = ("filename", "sha256", "mime", "size_bytes", "owner_kind", "doc_type", "status")


def doc_ref(doc: Document) -> str:
    return f"document:{doc.uuid}"


class DocumentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---- lookup / access -------------------------------------------------------------------
    def doc_or_404(self, doc_uuid: UUID | str) -> Document:
        doc_uuid = UUID(str(doc_uuid))
        doc = self.db.scalars(select(Document).where(Document.uuid == doc_uuid)).first()
        if doc is None:
            raise NotFoundError("document")
        return doc

    def ensure_access(self, request: Request | None, user, doc: Document) -> None:
        """Public documents: anyone holding the uuid. Bank/owner documents: signed-in users with access."""
        if doc.owner_kind == "public":
            return
        if user is None:
            raise AppException(code="unauthorized", status_code=401, detail="Sign in to view this document")
        if request is not None and not has_scope(request, user, Scope.DOCUMENT_READ):
            raise ForbiddenError("Missing scope document:read")
        if user.role in PORTFOLIO_ROLES:
            return
        if doc.uploaded_by == user.id:
            return
        if doc.borrower_id:
            b = self.db.get(Borrower, doc.borrower_id)
            if b is not None and b.owner_user_id == user.id:
                return
        raise ForbiddenError("This document belongs to another business")

    # ---- upload ------------------------------------------------------------------------------
    def upload(self, content: bytes, filename: str, *, owner_kind: str = "bank", borrower_id: int | None = None,
               actor=None, max_mb: int | None = None, priority: int = 0, payload_extra: dict | None = None,
               commit: bool = True) -> tuple[Document, Job]:
        """Stores the original, creates the document row and its analyse_document job in one transaction.
        Used by /analyse, /documents, /owner/files, /applications/{n}/documents and app.seed_demo."""
        max_mb = max_mb or (settings.PUBLIC_MAX_UPLOAD_MB if owner_kind == "public" else settings.BANK_MAX_UPLOAD_MB)
        if not content:
            raise AppException(code="empty_file", status_code=422, detail="The file is empty")
        if len(content) > max_mb * 1024 * 1024:
            raise AppException(code="file_too_large", status_code=413,
                               detail=f"File is larger than {max_mb} MB", params={"max_mb": max_mb})
        filename = (filename or "upload").replace("/", "_").replace("\\", "_")[:255]
        mime, ext = storage.detect_mime(content, filename)
        doc = Document(filename=filename, sha256=storage.sha256(content), mime=mime, size_bytes=len(content),
                       owner_kind=owner_kind, borrower_id=borrower_id,
                       uploaded_by=getattr(actor, "id", None), status="queued", summary={})
        if owner_kind == "public":
            doc.expires_at = utcnow() + timedelta(hours=settings.PUBLIC_RETENTION_HOURS)
        self.db.add(doc)
        self.db.flush()
        doc.storage_path = storage.save_original(str(doc.uuid), content, ext)
        jobs = JobService(self.db)
        payload = {"document_uuid": str(doc.uuid), "public": owner_kind == "public", **(payload_extra or {})}
        if mime not in storage.SUPPORTED:
            # Nothing for the pipeline to read: answer truthfully and immediately.
            doc.status = "failed"
            doc.failure_cause = (f"Unsupported file type ({ext.upper()}). Converza reads PDF, XLSX, JPG and PNG; "
                                 "export the document to one of these formats and upload it again.")
            doc.type_reason = "Not analysed: unsupported format"
            job = jobs.enqueue("analyse_document", payload, ref=doc_ref(doc), priority=priority)
            job.status, job.stage, job.progress = "done", "classify", 100
            job.started_at = job.finished_at = utcnow()
        else:
            deadline = (utcnow() + timedelta(seconds=settings.PUBLIC_DEADLINE_S)) if owner_kind == "public" else None
            job = jobs.enqueue("analyse_document", payload, ref=doc_ref(doc),
                               priority=PUBLIC_PRIORITY if owner_kind == "public" else priority,
                               deadline_at=deadline)
        audit.record(self.db, actor if actor is not None else ("public" if owner_kind == "public" else None),
                     "upload", "document", doc.uuid, after=audit.snapshot(doc, DOC_FIELDS))
        if commit:
            self.db.commit()
            self.db.refresh(doc)
            self.db.refresh(job)
        return doc, job

    # ---- output --------------------------------------------------------------------------------
    def page_count(self, doc: Document) -> int:
        return self.db.scalar(select(func.count(Page.id)).where(Page.document_id == doc.id)) or 0

    def page_or_404(self, doc: Document, n: int) -> Page:
        page = self.db.scalars(select(Page).where(Page.document_id == doc.id, Page.n == n)).first()
        if page is None or not page.image_path:
            raise NotFoundError("page")
        return page

    def dump(self, doc: Document) -> dict:
        return {
            "uuid": str(doc.uuid), "filename": doc.filename, "mime": doc.mime, "size_bytes": doc.size_bytes,
            "owner_kind": doc.owner_kind, "doc_type": doc.doc_type, "type_confidence": doc.type_confidence,
            "type_reason": doc.type_reason, "language": doc.language, "status": doc.status,
            "failure_cause": doc.failure_cause,
            "period_start": doc.period_start.isoformat() if doc.period_start else None,
            "period_end": doc.period_end.isoformat() if doc.period_end else None,
            "page_count": self.page_count(doc), "text_layer": doc.text_layer, "stir": doc.stir,
            "summary": {k: v for k, v in (doc.summary or {}).items() if k not in ("readable", "unmapped", "recurring")},
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        }

    def purge_expired_public(self) -> int:
        """Public uploads are deleted after PUBLIC_RETENTION_HOURS (files and rows)."""
        expired = self.db.scalars(select(Document).where(Document.owner_kind == "public",
                                                         Document.expires_at < utcnow())).all()
        for doc in expired:
            storage.delete_doc_files(str(doc.uuid))
            self.db.delete(doc)
        if expired:
            self.db.commit()
        return len(expired)
