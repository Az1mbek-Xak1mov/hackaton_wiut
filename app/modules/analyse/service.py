from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.modules.documents.models import Document
from app.modules.documents.service import DocumentService, doc_ref
from app.modules.extraction.models import Fact
from app.modules.extraction.service import FactSerializer
from app.modules.jobs.schemas import JobOut
from app.modules.jobs.service import JobService
from app.modules.reconcile.models import Finding
from app.modules.statements.service import preview


class AnalyseService:
    """The public jury path: any PDF/XLSX/JPG/PNG in, always a truthful answer out."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def submit(self, content: bytes, filename: str) -> dict:
        from app.modules.analyse.bundle import BundleService, Item, _is_zip
        if content and _is_zip(content, filename):   # a ZIP is a loan file: its members are analysed together
            return BundleService(self.db).submit([Item(filename, content)])
        doc, job = DocumentService(self.db).upload(content, filename, owner_kind="public")
        return {"uuid": str(doc.uuid), "kind": "document", "job": JobOut.model_validate(job).model_dump(mode="json")}

    def public_doc_or_404(self, doc_uuid: UUID) -> Document:
        doc = self.db.scalars(select(Document).where(Document.uuid == doc_uuid,
                                                     Document.owner_kind == "public")).first()
        if doc is None:
            raise NotFoundError("document", "Unknown or expired analysis (public uploads are kept 24 hours)")
        return doc

    def result(self, doc: Document) -> dict:
        s = DocumentService(self.db)
        job = JobService(self.db).latest_for(doc_ref(doc))
        facts = self.db.scalars(select(Fact).where(Fact.document_id == doc.id).order_by(Fact.page_n, Fact.id)).all()
        findings = self.db.scalars(select(Finding).where(Finding.document_id == doc.id).order_by(Finding.id)).all()
        summary = doc.summary or {}
        out = {
            "document": s.dump(doc),
            "job": JobOut.model_validate(job).model_dump(mode="json") if job else None,
            "facts": FactSerializer(self.db).many(facts),
            "unmapped": summary.get("unmapped", []),
            "findings": [{"uuid": str(f.uuid), "rule_id": f.rule_id, "severity": f.severity, "label": f.label,
                          "title": f.title, "detail": f.detail, "evidence": f.evidence, "state": f.state}
                         for f in findings],
            "transactions_preview": (preview(self.db, doc.id, summary.get("recurring"))
                                     if doc.doc_type == "bank_statement" else None),
            "readable": summary.get("readable"),
            "description": summary.get("description") or {"text": "", "mode": "none"},
            "partial": bool(summary.get("partial")),
        }
        return out
