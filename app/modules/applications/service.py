from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppException, ConflictError, NotFoundError
from app.modules.applications.models import Application, ApplicationDocument, Decision
from app.modules.audit import service as audit
from app.modules.borrowers.models import Borrower
from app.modules.borrowers.service import BorrowerService
from app.modules.documents.models import Document
from app.modules.documents.service import DocumentService
from app.modules.extraction.models import Fact
from app.modules.extraction.service import fact_to_draft
from app.modules.jobs.models import Job
from app.modules.jobs.service import JobService
from app.modules.statements.models import Transaction

STATUS_LABELS = {"processing": "Documents being analysed", "in_review": "With the bank — in review",
                 "waiting_on_applicant": "The bank asked for more documents", "decided": "Decision recorded"}
APP_FIELDS = ("number", "requested_amount", "term_months", "rate_pct", "purpose", "status", "received_on")
DECISION_FIELDS = ("outcome", "reasoning", "evidence_reviewed")

# Required set for rule R10 and the documents list (application, Form 1 ×2, Form 2 ×2, statement, tax declaration).
REQUIRED_DOCS = [
    ("loan_application", "Loan application form"),
    ("form1", "Form 1 — Balance sheet, last financial year"),
    ("form1", "Form 1 — Balance sheet, latest half-year"),
    ("form2", "Form 2 — Income statement, last financial year"),
    ("form2", "Form 2 — Income statement, latest half-year"),
    ("bank_statement", "Bank statement, last 8 months"),
    ("tax_declaration", "Tax declaration, latest quarter"),
]
# Stable keys for REQUIRED_DOCS (same order), used by the owner checklist so the UI can translate each item.
REQUIRED_KEYS = ["loan_application", "form1_fy", "form1_half", "form2_fy", "form2_half", "bank_statement",
                 "tax_declaration"]
FINAL_OUTCOMES = ("recommend", "decline")


def app_ref(application: Application) -> str:
    return f"application:{application.uuid}"


def linked_documents(db: Session, application: Application) -> list[Document]:
    return list(db.scalars(select(Document).join(ApplicationDocument, ApplicationDocument.document_id == Document.id)
                           .where(ApplicationDocument.application_id == application.id)
                           .order_by(Document.id)).all())


APPLICATION_PRIORITY = 5   # after public uploads (10), before bulk document jobs (0)


def enqueue_analysis(db: Session, application: Application, kind: str = "analyse_application") -> Job:
    jobs = JobService(db)
    pending = jobs.pending_for(app_ref(application), kind)
    if pending is not None:
        return pending
    return jobs.enqueue(kind, {"application_uuid": str(application.uuid)}, ref=app_ref(application),
                        priority=APPLICATION_PRIORITY)


def annuity_installment(amount_k: float | None, term_months: int | None, rate_pct: float | None) -> float | None:
    if not amount_k or not term_months:
        return None
    if not rate_pct:
        return float(amount_k) / term_months
    r = float(rate_pct) / 100.0 / 12.0
    return float(amount_k) * r / (1 - (1 + r) ** (-int(term_months)))


def application_context_dict(db: Session, application: Application) -> dict:
    borrower = db.get(Borrower, application.borrower_id)
    amount = float(application.requested_amount) if application.requested_amount is not None else None
    rate = float(application.rate_pct) if application.rate_pct is not None else None
    declared = dict(application.declared or {})
    return {
        **declared,   # e.g. declared_revenue_fy, declared_revenue_year, declared_debts (see pipeline AppContext)
        "number": application.number,
        "requested_amount": amount,
        "term_months": application.term_months,
        "rate_pct": rate,
        "installment": annuity_installment(amount, application.term_months, rate),
        "received_on": application.received_on,
        "borrower_stir": borrower.stir if borrower else None,
        "borrower_name": borrower.name if borrower else "",
        "purpose": application.purpose,
    }


def build_app_context(db: Session, application: Application, docs: list[Document], AppContext, make):
    from app.modules.jobs.runner import doc_context_dict
    from app.pipeline.types import TxnDraft

    doc_ids = [d.id for d in docs]
    facts = db.scalars(select(Fact).where(Fact.document_id.in_(doc_ids)).order_by(Fact.id)).all() if doc_ids else []
    txns = db.scalars(select(Transaction).where(Transaction.document_id.in_(doc_ids))
                      .order_by(Transaction.document_id, Transaction.row_n)).all() if doc_ids else []
    txn_drafts = [TxnDraft(row_n=t.row_n, booked_on=t.booked_on, amount=float(t.amount), counterparty=t.counterparty,
                           counterparty_stir=t.counterparty_stir, account=t.account, purpose=t.purpose,
                           category=t.category, category_source=t.category_source, category_conf=t.category_conf,
                           recurring_group=t.recurring_group) for t in txns]
    uuid_by_doc = {d.id: str(d.uuid) for d in docs}
    recurring = [r for d in docs if d.doc_type == "bank_statement" for r in ((d.summary or {}).get("recurring") or [])]
    return make(AppContext, facts=[fact_to_draft(f) for f in facts], transactions=txn_drafts,
                documents=[doc_context_dict(d) for d in docs], application=application_context_dict(db, application),
                recurring=recurring, fact_document={f.key: uuid_by_doc.get(f.document_id) for f in facts})


class ApplicationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def app_or_404(self, ref: str) -> Application:
        stmt = select(Application).where(Application.number == ref)
        app = self.db.scalars(stmt).first()
        if app is None:
            try:
                from uuid import UUID
                app = self.db.scalars(select(Application).where(Application.uuid == UUID(ref))).first()
            except ValueError:
                app = None
        if app is None:
            raise NotFoundError("application")
        return app

    def list_stmt(self):
        # public /analyse loan-file checks never enter the bank's queue
        return (select(Application).where(Application.is_public.is_(False))
                .order_by(Application.received_on.desc(), Application.id.desc()))

    def _next_number(self, year: int) -> str:
        prefix = f"APP-{year}-"
        existing = self.db.scalars(select(Application.number).where(Application.number.like(prefix + "%"))).all()
        seq = max([int(n.rsplit("-", 1)[-1]) for n in existing if n.rsplit("-", 1)[-1].isdigit()] or [0]) + 1
        return f"{prefix}{seq:04d}"

    def create_application(self, data: dict, actor) -> Application:
        borrower = BorrowerService(self.db).upsert_borrower(data["borrower"], actor, commit=False)
        number = data.get("number") or self._next_number((data.get("received_on") or date.today()).year)
        if self.db.scalars(select(Application).where(Application.number == number)).first():
            raise ConflictError("application_number_taken", f"Application {number} already exists")
        app = Application(number=number, borrower_id=borrower.id, requested_amount=data.get("requested_amount"),
                          term_months=data.get("term_months"), rate_pct=data.get("rate_pct"),
                          purpose=data.get("purpose") or "", collateral=data.get("collateral") or "",
                          declared=data.get("declared") or {}, status="processing",
                          received_on=data.get("received_on") or date.today())
        self.db.add(app)
        self.db.flush()
        audit.record(self.db, actor, "create", "application", app.uuid, after=audit.snapshot(app, APP_FIELDS))
        self.db.commit()
        self.db.refresh(app)
        return app

    def attach_upload(self, app: Application, content: bytes, filename: str, actor) -> tuple[Document, Job]:
        if app.status == "decided":
            raise AppException(code="application_decided", status_code=409, detail="The application is already decided")
        doc, job = DocumentService(self.db).upload(content, filename, owner_kind="bank", borrower_id=app.borrower_id,
                                                   actor=actor, payload_extra={"application_uuid": str(app.uuid)},
                                                   commit=False)
        self.db.add(ApplicationDocument(application_id=app.id, document_id=doc.id))
        if app.status != "processing":
            app.status = "processing"
        self.db.commit()
        self.db.refresh(doc)
        self.db.refresh(job)
        return doc, job

    def analyse(self, app: Application, actor) -> Job:
        job = enqueue_analysis(self.db, app)
        audit.record(self.db, actor, "analyse_request", "application", app.uuid)
        self.db.commit()
        self.db.refresh(job)
        return job

    def regenerate_narrative(self, app: Application, actor) -> Job:
        job = enqueue_analysis(self.db, app, kind="narrative")
        audit.record(self.db, actor, "narrative_request", "application", app.uuid)
        self.db.commit()
        self.db.refresh(job)
        return job

    def record_decision(self, app: Application, data: dict, actor) -> Decision:
        dec = Decision(application_id=app.id, officer_id=actor.id, outcome=data["outcome"],
                       reasoning=data["reasoning"], evidence_reviewed=list(data.get("evidence_reviewed") or []))
        self.db.add(dec)
        before = {"status": app.status}
        # "Request more information" hands the application back to the applicant; only a final outcome closes it.
        app.status = "waiting_on_applicant" if data["outcome"] == "request_info" else "decided"
        self.db.flush()
        audit.record(self.db, actor, "decision", "application", app.uuid, before=before,
                     after=audit.snapshot(dec, DECISION_FIELDS))
        self.db.commit()
        self.db.refresh(dec)
        return dec

    def create_owner_application(self, user, data: dict) -> tuple[Application, Job]:
        """A business owner applies from converza.uz with documents already uploaded and analysed."""
        from uuid import UUID as _UUID
        borrower = BorrowerService(self.db).owner_borrower(user)
        own = {d.uuid: d for d in self.db.scalars(select(Document).where(Document.borrower_id == borrower.id,
                                                                         Document.owner_kind == "owner")).all()}
        taken = set(self.db.scalars(select(ApplicationDocument.document_id)).all())
        if data.get("document_uuids"):
            docs = []
            for u in data["document_uuids"]:
                d = own.get(_UUID(str(u)))
                if d is None:
                    raise NotFoundError("document", f"Document {u} is not one of your uploads")
                docs.append(d)
        else:
            docs = [d for d in own.values() if d.status in ("analyzed", "clarification") and d.id not in taken]
        if not docs:
            raise AppException(code="no_documents", status_code=422,
                               detail="Upload and analyse your documents before applying")
        today = date.today()
        app = Application(number=self._next_number(today.year), borrower_id=borrower.id,
                          requested_amount=round(float(data["requested_amount_mln"]) * 1000.0, 2),
                          term_months=data["term_months"], purpose=data.get("purpose") or "",
                          status="processing", received_on=today, declared={"channel": "online"})
        self.db.add(app)
        self.db.flush()
        for d in sorted(docs, key=lambda d: d.id):
            self.db.add(ApplicationDocument(application_id=app.id, document_id=d.id))
        self.db.flush()
        audit.record(self.db, user, "create", "application", app.uuid,
                     after=audit.snapshot(app, APP_FIELDS) | {"documents": len(docs), "channel": "online"})
        job = enqueue_analysis(self.db, app)
        self.db.commit()
        self.db.refresh(app)
        return app, job

    def latest_decision(self, app: Application) -> Decision | None:
        return self.db.scalars(select(Decision).where(Decision.application_id == app.id)
                               .order_by(Decision.id.desc())).first()

    def owner_items(self, user) -> list[dict]:
        from app.core.formatting import kuzs_to_mln
        borrower = BorrowerService(self.db).owner_borrower(user)
        apps = self.db.scalars(select(Application).where(Application.borrower_id == borrower.id)
                               .order_by(Application.id.desc())).all()
        out = []
        for a in apps:
            docs = linked_documents(self.db, a)
            checklist = required_checklist(docs)
            dec = self.latest_decision(a)
            final = a.status == "decided" and (dec is None or dec.outcome in FINAL_OUTCOMES)
            out.append({"uuid": str(a.uuid), "number": a.number, "status": a.status,
                        "status_label": STATUS_LABELS.get(a.status, a.status),
                        "requested_display": kuzs_to_mln(a.requested_amount) if a.requested_amount is not None else "n/a",
                        "requested_unit": "mln UZS", "term_months": a.term_months, "purpose": a.purpose,
                        "received_on": a.received_on.isoformat(), "documents": len(docs),
                        "analysed_at": a.analysed_at.isoformat() if a.analysed_at else None,
                        # 1 upload · 2 send · 3 bank officer reviews · 4 decision
                        "step": 4 if final else 3,
                        # waiting on the applicant (older records stored a request for information as "decided")
                        "action_needed": a.status == "waiting_on_applicant" or (a.status == "decided" and not final),
                        "can_add_documents": not final,
                        "missing_documents": [{"key": c["key"], "title": c["title"]} for c in checklist
                                              if not c["present"]],
                        # written by the officer (H5); the system never fills it
                        "decision": ({"outcome": dec.outcome, "message": dec.reasoning,
                                      "decided_at": dec.created_at.isoformat() if dec.created_at else None}
                                     if dec is not None else None)})
        return out

    def owner_checklist(self, user) -> dict:
        borrower = BorrowerService(self.db).owner_borrower(user)
        docs = self.db.scalars(select(Document).where(Document.borrower_id == borrower.id)
                               .order_by(Document.id)).all()
        items = required_checklist(list(docs))
        return {"items": items, "present": sum(1 for i in items if i["present"]), "total": len(items)}

    def add_owner_documents(self, user, ref: str, document_uuids: list | None) -> tuple[Application, Job]:
        """The applicant adds documents to an open application (typically after the bank asked for more)."""
        from uuid import UUID as _UUID
        borrower = BorrowerService(self.db).owner_borrower(user)
        try:
            app = self.db.scalars(select(Application).where(Application.uuid == _UUID(str(ref)),
                                                            Application.borrower_id == borrower.id)).first()
        except ValueError:
            app = None
        if app is None:
            raise NotFoundError("application")
        dec = self.latest_decision(app)
        if app.status == "decided" and (dec is None or dec.outcome in FINAL_OUTCOMES):
            raise AppException(code="application_decided", status_code=409,
                               detail="The bank has already recorded a decision on this application")
        linked = {d.id for d in linked_documents(self.db, app)}
        own = {d.uuid: d for d in self.db.scalars(select(Document).where(Document.borrower_id == borrower.id,
                                                                         Document.owner_kind == "owner")).all()}
        if document_uuids:
            docs = []
            for u in document_uuids:
                d = own.get(_UUID(str(u)))
                if d is None:
                    raise NotFoundError("document", f"Document {u} is not one of your uploads")
                if d.id not in linked:
                    docs.append(d)
        else:
            docs = [d for d in own.values() if d.status in ("analyzed", "clarification") and d.id not in linked]
        if not docs:
            raise AppException(code="no_documents", status_code=422,
                               detail="No new analysed documents to add. Upload the requested documents first")
        for d in sorted(docs, key=lambda d: d.id):
            self.db.add(ApplicationDocument(application_id=app.id, document_id=d.id))
        before = {"status": app.status}
        app.status = "processing"
        self.db.flush()
        audit.record(self.db, user, "add_documents", "application", app.uuid, before=before,
                     after={"status": app.status, "documents": len(docs)})
        job = enqueue_analysis(self.db, app)
        self.db.commit()
        self.db.refresh(app)
        return app, job

    def docs_count(self, app: Application) -> tuple[int, int]:
        docs = linked_documents(self.db, app)
        present = present_required(docs)
        return sum(1 for ok in present if ok), len(REQUIRED_DOCS)

    def list_items(self) -> list[dict]:
        from app.core.formatting import kuzs_to_mln
        from app.modules.reconcile.models import Finding

        apps = self.db.scalars(self.list_stmt()).all()
        borrowers = {b.id: b for b in self.db.scalars(select(Borrower).where(
            Borrower.id.in_({a.borrower_id for a in apps}))).all()} if apps else {}
        counts = dict(self.db.execute(select(Finding.application_id, func.count(Finding.id))
                                      .where(Finding.state == "open", Finding.application_id.is_not(None),
                                             or_(Finding.severity == "attn", Finding.severity == "watch",
                                                 Finding.severity == "neutral"))
                                      .group_by(Finding.application_id)).all())
        items = []
        for a in apps:
            b = borrowers.get(a.borrower_id)
            present, total = self.docs_count(a)
            n_issues = counts.get(a.id, 0)
            items.append({
                "uuid": str(a.uuid), "number": a.number, "name": b.name if b else "", "industry": b.industry if b else "",
                "requested_display": kuzs_to_mln(a.requested_amount) if a.requested_amount is not None else "n/a",
                "term_months": a.term_months, "received_on": a.received_on.isoformat(),
                "docs": f"{present}/{total}", "status": a.status,
                "issues_count": n_issues,
                "issues_label": (f"{n_issues} issue{'s' if n_issues != 1 else ''}" if n_issues else ""),
            })
        return items


def present_required(docs: list[Document]) -> list[bool]:
    """Greedy match of uploaded documents to the required list (two Form 1s, two Form 2s)."""
    pool: dict[str, int] = {}
    for d in docs:
        if d.status != "failed":
            pool[d.doc_type] = pool.get(d.doc_type, 0) + 1
    out = []
    for doc_type, _title in REQUIRED_DOCS:
        if pool.get(doc_type, 0) > 0:
            pool[doc_type] -= 1
            out.append(True)
        else:
            out.append(False)
    return out


def required_checklist(docs: list[Document]) -> list[dict]:
    """The required list with the document matched to each item, using the same counting as present_required (R10).
    Within a type the earlier period fills the earlier item (last financial year before latest half-year)."""
    present = present_required(docs)
    pool: dict[str, list[Document]] = {}
    for d in sorted((d for d in docs if d.status != "failed"),
                    key=lambda d: (d.period_end is None, d.period_end or date.min, d.id)):
        pool.setdefault(d.doc_type, []).append(d)
    out = []
    for key, (doc_type, title), ok in zip(REQUIRED_KEYS, REQUIRED_DOCS, present):
        d = pool[doc_type].pop(0) if ok else None
        out.append({"key": key, "doc_type": doc_type, "title": title, "present": ok,
                    "state": ("missing" if d is None else "reading" if d.status in ("queued", "processing")
                              else "ready"),
                    "document": ({"uuid": str(d.uuid), "filename": d.filename, "status": d.status,
                                  "period_start": d.period_start.isoformat() if d.period_start else None,
                                  "period_end": d.period_end.isoformat() if d.period_end else None}
                                 if d is not None else None)})
    return out
