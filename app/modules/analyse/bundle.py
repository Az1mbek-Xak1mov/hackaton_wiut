"""Public loan-file check: several files (or one ZIP) from /analyse analysed together as one application.

The files become public documents (24 h retention) linked to a temporary application flagged `is_public`, so the
same cross-document rules (R01–R12), ratios and verified narrative run as for a bank application. The flag keeps
it out of the bank's queue and portfolio; the worker deletes it with its documents when it expires.
"""
import io
import secrets
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppException, NotFoundError
from app.core.timeutil import aware, utcnow
from app.modules.applications.models import Application, ApplicationDocument
from app.modules.applications.service import app_ref, enqueue_analysis, linked_documents, required_checklist
from app.modules.audit import service as audit
from app.modules.borrowers.models import Borrower
from app.modules.documents import storage
from app.modules.documents.models import Document
from app.modules.documents.service import DocumentService, doc_ref
from app.modules.jobs.schemas import JobOut
from app.modules.jobs.service import JobService

MAX_FILES = 12
MAX_FILE_MB = 20
MAX_TOTAL_MB = 40
MB = 1024 * 1024
TERMINAL = {"analyzed", "clarification", "failed"}
PLACEHOLDER_NAME = "Uploaded loan file"


@dataclass
class Item:
    filename: str
    content: bytes


def _clean_name(name: str) -> str:
    """Base name only: archive paths never reach the file system (files are stored under the document uuid)."""
    base = PurePosixPath((name or "").replace("\\", "/")).name
    return (base or "upload")[:255]


def _is_zip(content: bytes, filename: str) -> bool:
    return storage.detect_mime(content, filename)[0] == "application/zip"


def expand(uploads: list[Item]) -> tuple[list[Item], list[dict]]:
    """ZIP archives fan out into their members. Returns (files to analyse, skipped files with the reason).
    Caps: MAX_FILES analysed files, MAX_FILE_MB each, MAX_TOTAL_MB in total (uncompressed sizes, read with a
    hard limit so a zip bomb cannot exceed them); nested archives, folders and encrypted members are skipped."""
    out: list[Item] = []
    skipped: list[dict] = []
    total = 0

    def take(name: str, content: bytes) -> None:
        nonlocal total
        mime, ext = storage.detect_mime(content, name)
        if not content:
            skipped.append({"filename": name, "reason": "empty file"})
        elif mime == "application/zip":
            skipped.append({"filename": name, "reason": "archive inside an archive; unzip it first"})
        elif mime not in storage.SUPPORTED:
            skipped.append({"filename": name, "reason": f"unsupported file type ({ext.upper()})"})
        elif len(out) >= MAX_FILES:
            skipped.append({"filename": name, "reason": f"over the limit of {MAX_FILES} files per loan file"})
        elif total + len(content) > MAX_TOTAL_MB * MB:
            skipped.append({"filename": name, "reason": f"over the {MAX_TOTAL_MB} MB limit per loan file"})
        else:
            total += len(content)
            out.append(Item(name, content))

    for up in uploads:
        name = _clean_name(up.filename)
        if not _is_zip(up.content, name):
            take(name, up.content)
            continue
        try:
            zf = zipfile.ZipFile(io.BytesIO(up.content))
            members = zf.infolist()
        except (zipfile.BadZipFile, ValueError):
            skipped.append({"filename": name, "reason": "damaged ZIP archive"})
            continue
        for m in members:
            mname = _clean_name(m.filename)
            parts = PurePosixPath(m.filename.replace("\\", "/")).parts
            if m.is_dir() or "__MACOSX" in parts or mname.startswith("."):
                continue
            if m.flag_bits & 0x1:
                skipped.append({"filename": mname, "reason": "password-protected"})
                continue
            if m.file_size > MAX_FILE_MB * MB:
                skipped.append({"filename": mname, "reason": f"larger than {MAX_FILE_MB} MB"})
                continue
            if total + m.file_size > MAX_TOTAL_MB * MB:
                skipped.append({"filename": mname, "reason": f"over the {MAX_TOTAL_MB} MB limit per loan file"})
                continue
            if len(out) >= MAX_FILES:
                skipped.append({"filename": mname, "reason": f"over the limit of {MAX_FILES} files per loan file"})
                continue
            try:
                with zf.open(m) as fh:
                    data = fh.read(MAX_FILE_MB * MB + 1)   # never trust the header's size alone
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError):
                skipped.append({"filename": mname, "reason": "could not be extracted"})
                continue
            if len(data) > MAX_FILE_MB * MB:
                skipped.append({"filename": mname, "reason": f"larger than {MAX_FILE_MB} MB"})
                continue
            take(mname, data)
    return out, skipped


class BundleService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---- create ----------------------------------------------------------------------------
    def submit(self, uploads: list[Item]) -> dict:
        if not uploads:
            raise AppException(code="no_files", status_code=422, detail="Choose at least one file")
        if sum(len(u.content) for u in uploads) > MAX_TOTAL_MB * MB:
            raise AppException(code="bundle_too_large", status_code=413,
                               detail=f"The files are larger than {MAX_TOTAL_MB} MB together",
                               params={"max_mb": MAX_TOTAL_MB})
        files, skipped = expand(uploads)
        if not files:
            raise AppException(code="no_supported_files", status_code=422,
                               detail="None of the files can be analysed. Converza reads PDF, Excel, JPG and PNG "
                                      "(also inside a ZIP)", params={"skipped": skipped})
        now = utcnow()
        expires = now + timedelta(hours=settings.PUBLIC_RETENTION_HOURS)
        borrower = Borrower(name=PLACEHOLDER_NAME, is_public=True, is_synthetic=False)
        self.db.add(borrower)
        self.db.flush()
        app = Application(number=f"PUB-{secrets.token_hex(5).upper()}", borrower_id=borrower.id,
                          status="processing", received_on=date.today(), is_public=True, expires_at=expires,
                          declared={"channel": "public", "skipped": skipped})
        self.db.add(app)
        self.db.flush()
        docs = DocumentService(self.db)
        conc = max(1, settings.WORKER_CONCURRENCY)
        out_docs = []
        for i, f in enumerate(files):
            doc, job = docs.upload(f.content, f.filename, owner_kind="public",
                                   payload_extra={"application_uuid": str(app.uuid)}, commit=False)
            if job.deadline_at is not None:   # files wait their turn: each wave gets the full public time budget
                job.deadline_at = now + timedelta(seconds=settings.PUBLIC_DEADLINE_S * (1 + i // conc))
            self.db.add(ApplicationDocument(application_id=app.id, document_id=doc.id))
            out_docs.append(doc)
        self.db.flush()
        job = enqueue_analysis(self.db, app)
        audit.record(self.db, "public", "create", "application", app.uuid,
                     after={"channel": "public", "documents": len(files), "skipped": len(skipped)})
        self.db.commit()
        self.db.refresh(app)
        return {"uuid": str(app.uuid), "kind": "bundle",
                "documents": [self._doc_out(d) for d in out_docs], "skipped": skipped,
                "job": JobOut.model_validate(job).model_dump(mode="json")}

    # ---- read ------------------------------------------------------------------------------
    def bundle_or_404(self, uuid) -> Application:
        app = self.db.scalars(select(Application).where(Application.uuid == uuid,
                                                        Application.is_public.is_(True))).first()
        if app is None or (app.expires_at is not None and aware(app.expires_at) < utcnow()):
            raise NotFoundError("application", "Unknown or expired loan file (public uploads are kept 24 hours)")
        return app

    def _doc_out(self, d: Document, with_job: bool = False) -> dict:
        out = {"uuid": str(d.uuid), "filename": d.filename, "doc_type": d.doc_type, "status": d.status,
               "type_reason": d.type_reason, "failure_cause": d.failure_cause, "size_bytes": d.size_bytes,
               "period_start": d.period_start.isoformat() if d.period_start else None,
               "period_end": d.period_end.isoformat() if d.period_end else None,
               "partial": bool((d.summary or {}).get("partial"))}
        if with_job:
            job = JobService(self.db).latest_for(doc_ref(d))
            out["job"] = ({"status": job.status, "stage": job.stage, "progress": job.progress} if job else None)
        return out

    def result(self, app: Application) -> dict:
        from app.modules.applications.review import build_review

        docs = linked_documents(self.db, app)
        job = JobService(self.db).latest_for(app_ref(app))
        docs_done = all(d.status in TERMINAL for d in docs)
        state = job.status if job else "queued"
        status = ("done" if state == "done" else "failed" if state == "failed"
                  else "analysing" if docs_done else "reading")
        checklist = required_checklist(docs)
        out = {
            "uuid": str(app.uuid),
            "expires_at": app.expires_at.isoformat() if app.expires_at else None,
            "status": status,
            "job": JobOut.model_validate(job).model_dump(mode="json") if job else None,
            "documents": [self._doc_out(d, with_job=True) for d in docs],
            "skipped": list((app.declared or {}).get("skipped") or []),
            "required": [{"key": c["key"], "doc_type": c["doc_type"], "title": c["title"], "present": c["present"],
                          "document_uuid": c["document"]["uuid"] if c["document"] else None} for c in checklist],
            "missing": [{"key": c["key"], "title": c["title"]} for c in checklist if not c["present"]],
            "review": None,
        }
        if status == "done" and app.analysed_at is not None:
            v = build_review(self.db, app)
            out["review"] = {k: v[k] for k in ("request", "columns", "issues", "findings", "figures", "ratios",
                                               "indicator", "narrative", "facts")}
        return out

    # ---- retention -------------------------------------------------------------------------
    def purge_expired(self) -> int:
        """Expired public loan files: the application and its placeholder business (documents are purged by
        DocumentService.purge_expired_public with the same 24-hour expiry)."""
        expired = self.db.scalars(select(Application).where(Application.is_public.is_(True),
                                                            Application.expires_at < utcnow())).all()
        for app in expired:
            borrower = self.db.get(Borrower, app.borrower_id)
            for d in linked_documents(self.db, app):
                if d.owner_kind == "public":
                    storage.delete_doc_files(str(d.uuid))
                    self.db.delete(d)
            self.db.delete(app)
            self.db.flush()
            if borrower is not None and borrower.is_public:
                self.db.delete(borrower)
        if expired:
            self.db.commit()
        return len(expired)
