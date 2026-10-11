"""Job runner: calls the pure pipeline stages and persists their drafts.

Each stage writes `stage`, `progress` and its duration into `stage_timings` and commits, so the UI polls real
progress and latency p50/p95 comes from these rows. Pipeline modules are imported lazily: the API boots and
`/health` answers even if a pipeline module is missing in this build.
"""
from __future__ import annotations

import dataclasses
import importlib
import inspect
import logging
import time
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db_context
from app.core.timeutil import aware, utcnow
from app.modules.audit import service as audit
from app.modules.documents import storage
from app.modules.documents.models import Document, Page
from app.modules.extraction.models import Fact
from app.modules.extraction.service import fact_to_draft, persist_facts
from app.modules.jobs.models import Job
from app.modules.jobs.service import JobService, past_deadline

logger = logging.getLogger(__name__)

TERMINAL_DOC = {"analyzed", "clarification", "failed"}
FORM_TYPES = {"form1", "form2"}
DOC_INTRINSIC_RULES = {"R01", "R02", "R03"}   # rules that make sense for a single public/owner document
APPLICATION_WAIT_LIMIT_S = 20 * 60


class PipelineMissing(RuntimeError):
    pass


def pipeline_fn(module: str, name: str):
    try:
        mod = importlib.import_module(module)
    except ImportError as exc:
        raise PipelineMissing(f"{module} is not available in this build ({exc})") from exc
    fn = getattr(mod, name, None)
    if fn is None:
        raise PipelineMissing(f"{module}.{name} is not available in this build")
    return fn


def optional_fn(module: str, name: str):
    try:
        return pipeline_fn(module, name)
    except PipelineMissing:
        return None


def make(cls, **kwargs):
    """Builds a pipeline context object passing only the fields it declares; extra values are set as attributes
    when the object allows it. Keeps the runner tolerant while the pipeline contract settles."""
    if dataclasses.is_dataclass(cls):
        names = {f.name for f in dataclasses.fields(cls)}
    else:
        names = set(inspect.signature(cls).parameters)
    obj = cls(**{k: v for k, v in kwargs.items() if k in names})
    for k, v in kwargs.items():
        if k not in names:
            try:
                setattr(obj, k, v)
            except Exception:
                pass
    return obj


def call(fn, *args, **kwargs):
    """Calls `fn` with only the keyword arguments it accepts."""
    params = inspect.signature(fn).parameters
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kwargs)
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


def _jsonable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _jsonable(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (date,)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, float) and obj != obj:  # NaN
        return None
    if hasattr(obj, "__float__") and not isinstance(obj, (int, float, bool)):
        try:
            return float(obj)
        except Exception:
            return str(obj)
    return obj


class Stages:
    def __init__(self, db: Session, job: Job) -> None:
        self.db, self.job = db, job
        self.stage: str | None = None
        self.t0 = 0.0

    def start(self, stage: str, progress: int) -> None:
        self._close()
        self.job.stage = stage
        self.job.progress = progress
        self.job.locked_at = utcnow()          # heartbeat: keeps the lock fresh during long jobs
        self.db.commit()
        self.stage, self.t0 = stage, time.perf_counter()

    def _close(self) -> None:
        if self.stage:
            ms = int((time.perf_counter() - self.t0) * 1000)
            timings = dict(self.job.stage_timings or {})
            timings[self.stage] = timings.get(self.stage, 0) + ms
            self.job.stage_timings = timings
            self.stage = None

    def finish(self) -> None:
        self._close()
        timings = dict(self.job.stage_timings or {})
        timings["total"] = sum(v for k, v in timings.items() if k != "total")
        self.job.stage_timings = timings

    def late(self) -> bool:
        return past_deadline(self.job)


# ---------------------------------------------------------------------------------------- entry point

def run_job(job_id: int) -> None:
    with get_db_context() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        st = Stages(db, job)
        handler = HANDLERS.get(job.kind)
        try:
            if handler is None:
                raise RuntimeError(f"unknown job kind {job.kind!r}")
            outcome = handler(db, job, st)
            if outcome == "deferred":
                return
            st.finish()
            job.status, job.progress, job.finished_at = "done", 100, utcnow()
            db.commit()
        except Exception as exc:  # the job fails, the worker loop lives on
            db.rollback()
            logger.exception("job %s (%s) failed at stage %s", job_id, job.kind, job.stage)
            job = db.get(Job, job_id)
            st.job = job
            st.finish()
            job.status, job.finished_at = "failed", utcnow()
            job.error = f"{exc.__class__.__name__}: {exc}"[:2000]
            try:
                _on_failure(db, job, exc)
            except Exception:
                logger.exception("failure handler for job %s failed", job_id)
            db.commit()


def _on_failure(db: Session, job: Job, exc: Exception) -> None:
    if job.kind == "analyse_document":
        doc = _doc(db, job.payload.get("document_uuid"))
        if doc is not None:
            doc.status = "failed"
            if isinstance(exc, PipelineMissing):
                doc.failure_cause = "Document analysis is not available in this build: " + str(exc)
            else:
                doc.failure_cause = (f"Processing stopped during '{job.stage or 'start'}' "
                                     f"({exc.__class__.__name__}). What could be read is shown below.")
            db.flush()
            _maybe_enqueue_applications(db, doc)   # the application still gets analysed, with this gap visible
    elif job.kind == "monitoring_run":
        from app.modules.monitoring.models import MonitoringRun
        run = db.scalars(select(MonitoringRun).where(MonitoringRun.uuid == UUID(job.payload["run_uuid"]))).first()
        if run is not None:
            run.status, run.finished_at = "failed", utcnow()


def _doc(db: Session, uuid: str | None) -> Document | None:
    if not uuid:
        return None
    return db.scalars(select(Document).where(Document.uuid == UUID(str(uuid)))).first()


# ---------------------------------------------------------------------------------------- analyse_document

def handle_analyse_document(db: Session, job: Job, st: Stages):
    doc = _doc(db, job.payload.get("document_uuid"))
    if doc is None:
        raise RuntimeError("document not found")
    public = doc.owner_kind == "public"
    doc.status = "processing"
    st.start("parse", 5)

    parse_document = pipeline_fn("app.pipeline.parse", "parse_document")
    deadline_epoch = None
    if job.deadline_at is not None:
        deadline_epoch = time.time() + max(1.0, (aware(job.deadline_at) - utcnow()).total_seconds())
    out_dir = storage.doc_dir(str(doc.uuid))
    parsed = call(parse_document, str(storage.abs_path(doc.storage_path)), doc.mime, str(out_dir),
                  max_ocr_pages=settings.PUBLIC_MAX_OCR_PAGES if public else settings.BANK_MAX_OCR_PAGES,
                  deadline=deadline_epoch, filename=doc.filename or "")
    _store_parsed(db, doc, parsed)
    summary = dict(doc.summary or {})
    summary["kind"] = parsed.kind
    if parsed.partial:
        summary["partial"] = True

    st.start("readable", 55)
    readable_summary = optional_fn("app.pipeline.readable", "readable_summary")
    if readable_summary is not None:
        try:
            summary["readable"] = _jsonable(readable_summary(parsed))
        except Exception:
            logger.exception("readable_summary failed for %s", doc.uuid)
    doc.summary = summary
    db.commit()

    facts: list[Fact] = []
    # re-runs (stale-lock requeue, manual re-analysis) replace what this document produced before
    from app.modules.statements.models import Transaction
    db.execute(delete(Fact).where(Fact.document_id == doc.id))
    db.execute(delete(Transaction).where(Transaction.document_id == doc.id))
    if parsed.failure_cause and not parsed.pages and not parsed.sheets:
        pass  # nothing more to read
    elif st.late():
        summary["partial"] = True
    elif parsed.doc_type in FORM_TYPES:
        st.start("extract", 65)
        extract_forms = pipeline_fn("app.pipeline.extract_forms", "extract_forms")
        drafts, unmapped = extract_forms(parsed)
        if unmapped:   # LLM fallback for rows the dictionary could not map (skipped when the LLM is off)
            try:
                from app.modules.llm.unmapped import resolve_unmapped
                extra, unmapped = resolve_unmapped(db, parsed.doc_type, drafts, unmapped,
                                                   max_rows=8 if public else 20,
                                                   deadline=(deadline_epoch - 10) if deadline_epoch else None,
                                                   document_id=doc.id)
                drafts = list(drafts) + extra
            except Exception:
                logger.exception("unmapped-line fallback failed for %s", doc.uuid)
        facts, _ = persist_facts(db, drafts, document=doc)
        summary["unmapped"] = _jsonable(unmapped or [])
        summary["fields"] = len(facts)
        summary["unmapped_count"] = len(unmapped or [])
        if facts:
            summary["avg_confidence"] = round(sum(f.confidence for f in facts) / len(facts), 3)
            summary["low_confidence"] = sum(1 for f in facts if f.confidence < 0.80)
    elif parsed.doc_type == "loan_application":
        st.start("extract", 65)
        extract_application = pipeline_fn("app.pipeline.extract_application", "extract_application")
        facts, _ = persist_facts(db, extract_application(parsed), document=doc)
        summary["fields"] = len(facts)
    elif parsed.doc_type == "cash_flow":
        st.start("extract", 65)
        extract_cashflow = pipeline_fn("app.pipeline.cashflow", "extract_cashflow")
        facts, _ = persist_facts(db, extract_cashflow(parsed), document=doc)
        summary["fields"] = len(facts)
    elif parsed.doc_type == "bank_statement":
        st.start("normalise", 65)
        normalise_statement = pipeline_fn("app.pipeline.statements", "normalise_statement")
        own_stir = _own_stir(db, doc) or parsed.stir
        txns, drafts, recurring = normalise_statement(parsed, own_stir)
        _store_transactions(db, doc, txns)
        facts, remap = persist_facts(db, drafts, document=doc)
        rec = _jsonable(recurring or [])
        for r in rec:   # recurring groups cite aggregate facts
            if isinstance(r, dict) and isinstance(r.get("evidence"), list):
                r["evidence"] = [remap.get(k, k) for k in r["evidence"]]
        summary["recurring"] = rec
        summary["transactions"] = len(txns)
        summary["categories"] = len({t.category for t in txns})
        summary["uncategorised"] = sum(1 for t in txns if t.category == "other")
    doc.summary = summary
    db.commit()

    # Single-document arithmetic checks (balance sheet balances, P&L chain) for public/owner uploads.
    if facts and doc.doc_type in FORM_TYPES and not _application_ids(db, doc) and not st.late():
        st.start("reconcile", 85)
        _doc_level_rules(db, doc, facts)

    if public and not st.late():
        describe = optional_fn("app.modules.llm.describe", "describe_document")
        if describe is not None:
            st.start("describe", 92)
            # isolated in a savepoint: a failed insert here (e.g. a value the facts table cannot hold) rolls back
            # only the description, and the analysis that was already read stays "done"
            try:
                with db.begin_nested():
                    description = describe(db, doc)
            except Exception:
                logger.exception("describe_document failed for %s", doc.uuid)
                description = {"text": "", "mode": "none", "note": "description not available for this document"}
            summary = dict(doc.summary or {})
            summary["description"] = description
            doc.summary = summary

    doc.status = _final_status(doc, facts)
    if st.late():
        summary = dict(doc.summary or {})
        summary["partial"] = True
        doc.summary = summary
    db.commit()

    _maybe_enqueue_applications(db, doc)


def _store_parsed(db: Session, doc: Document, parsed) -> None:
    doc.doc_type = parsed.doc_type or "unknown"
    doc.type_confidence = float(parsed.type_confidence or 0.0)
    doc.type_reason = parsed.type_reason or ""
    doc.language = (parsed.language or "")[:16]
    doc.text_layer = bool(parsed.text_layer)
    doc.failure_cause = parsed.failure_cause or ""
    doc.period_start = parsed.period_start
    doc.period_end = parsed.period_end
    if parsed.stir:
        doc.stir = str(parsed.stir)[:9]
    db.execute(delete(Page).where(Page.document_id == doc.id))
    for p in parsed.pages:
        db.add(Page(document_id=doc.id, n=p.n, width=float(p.width or 0), height=float(p.height or 0),
                    image_path=storage.rel_path(p.image_path) if p.image_path else "",
                    image_scale=float(p.image_scale or 1.0), ocr_used=bool(p.ocr_used), ocr_mean_conf=p.ocr_mean_conf,
                    skew_deg=p.skew_deg, blur_score=p.blur_score,
                    words=[[w.text, round(w.x0, 2), round(w.y0, 2), round(w.x1, 2), round(w.y1, 2), round(w.conf, 3)]
                           for w in p.words]))
    db.flush()
    db.expire(doc, ["pages"])


def _store_transactions(db: Session, doc: Document, txns) -> None:
    from app.modules.statements.models import Transaction

    db.execute(delete(Transaction).where(Transaction.document_id == doc.id))
    for t in txns:
        stir = (t.counterparty_stir or None)
        db.add(Transaction(document_id=doc.id, row_n=int(t.row_n), booked_on=t.booked_on, amount=float(t.amount),
                           counterparty=(t.counterparty or "")[:255], counterparty_stir=stir[:9] if stir else None,
                           account=(t.account or None) and str(t.account)[:20], purpose=t.purpose or "",
                           category=(t.category or "other")[:32], category_source=(t.category_source or "rule")[:8],
                           category_conf=float(t.category_conf if t.category_conf is not None else 1.0),
                           recurring_group=(t.recurring_group or None) and str(t.recurring_group)[:64]))
    db.flush()


def _own_stir(db: Session, doc: Document) -> str | None:
    if doc.borrower_id:
        from app.modules.borrowers.models import Borrower
        b = db.get(Borrower, doc.borrower_id)
        return b.stir if b else None
    return None


def _final_status(doc: Document, facts: list[Fact]) -> str:
    if doc.failure_cause:
        return "failed"
    if any(f.confidence < 0.80 for f in facts if f.kind == "extracted"):
        return "clarification"
    return "analyzed"


def _application_ids(db: Session, doc: Document) -> list[int]:
    from app.modules.applications.models import ApplicationDocument
    return list(db.scalars(select(ApplicationDocument.application_id)
                           .where(ApplicationDocument.document_id == doc.id)).all())


def doc_context_dict(doc: Document) -> dict:
    return {"uuid": str(doc.uuid), "filename": doc.filename, "doc_type": doc.doc_type,
            "period_start": doc.period_start, "period_end": doc.period_end, "stir": doc.stir, "sha256": doc.sha256,
            "id": doc.id}


def _doc_level_rules(db: Session, doc: Document, facts: list[Fact]) -> None:
    from app.modules.reconcile.models import Finding
    rules_mod = optional_fn("app.pipeline.rules", "run_application_rules")
    AppContext = optional_fn("app.pipeline.rules", "AppContext")
    if rules_mod is None or AppContext is None:
        return
    ctx = make(AppContext, facts=[fact_to_draft(f) for f in facts], transactions=[],
               documents=[doc_context_dict(doc)], application={},
               fact_document={f.key: str(doc.uuid) for f in facts})
    try:
        found = [f for f in (rules_mod(ctx) or []) if f.rule_id in DOC_INTRINSIC_RULES]
    except Exception:
        logger.exception("document-level rules failed for %s", doc.uuid)
        return
    db.execute(delete(Finding).where(Finding.document_id == doc.id, Finding.application_id.is_(None)))
    cited = {k for f in found for k in (f.evidence or [])}
    derived = [d for d in getattr(ctx, "derived_facts", []) or [] if d.key in cited]
    _, remap = persist_facts(db, derived, document=doc, attach_computed=True)
    for f in found:
        f.evidence = [remap.get(k, k) for k in (f.evidence or [])]
        db.add(_finding_row(f, document_id=doc.id))
    db.flush()


def _finding_row(f, **fk):
    from app.modules.reconcile.models import Finding
    return Finding(rule_id=(f.rule_id or "")[:8], severity=(f.severity or "info")[:8], label=(f.label or "")[:48],
                   title=(f.title or "")[:255], detail=f.detail or "", evidence=list(f.evidence or []),
                   params=_jsonable(f.params or {}), **fk)


def _maybe_enqueue_applications(db: Session, doc: Document) -> None:
    """When the last document of an application finishes, its analysis starts by itself."""
    from app.modules.applications.models import Application
    from app.modules.applications.service import enqueue_analysis, linked_documents

    for app_id in _application_ids(db, doc):
        application = db.get(Application, app_id)
        if application is None:
            continue
        docs = linked_documents(db, application)
        if docs and all(d.status in TERMINAL_DOC for d in docs):
            enqueue_analysis(db, application)
    db.commit()


# ---------------------------------------------------------------------------------------- analyse_application

def handle_analyse_application(db: Session, job: Job, st: Stages):
    from app.modules.applications.models import Application
    from app.modules.applications.service import build_app_context, linked_documents

    application = db.scalars(select(Application).where(Application.uuid == UUID(job.payload["application_uuid"]))).first()
    if application is None:
        raise RuntimeError("application not found")
    docs = linked_documents(db, application)
    pending = [d for d in docs if d.status not in TERMINAL_DOC]
    waited = (utcnow() - aware(job.created_at)).total_seconds() if job.created_at else 0
    if pending and waited < APPLICATION_WAIT_LIMIT_S:
        job.status, job.run_after = "queued", utcnow() + timedelta(seconds=3)
        job.attempts = max(0, (job.attempts or 1) - 1)
        job.stage = "waiting_for_documents"
        db.commit()
        return "deferred"

    run_application_rules = pipeline_fn("app.pipeline.rules", "run_application_rules")
    AppContext = pipeline_fn("app.pipeline.rules", "AppContext")
    compute_ratios = pipeline_fn("app.pipeline.ratios", "compute_ratios")

    st.start("reconcile", 20)
    _fill_application_from_facts(db, application, docs)
    ctx = build_app_context(db, application, docs, AppContext, make)

    from app.modules.reconcile.models import Finding
    findings = list(run_application_rules(ctx) or [])
    try:
        setattr(ctx, "findings", findings)
    except Exception:
        pass

    st.start("ratios", 55)
    ratio_drafts = list(compute_ratios(ctx) or [])

    # Persist: application-level facts (ratios + every number the rules derived), then findings citing them.
    previous = {(f.rule_id, f.title): (f.state, f.state_note)
                for f in db.scalars(select(Finding).where(Finding.application_id == application.id)).all()}
    db.execute(delete(Finding).where(Finding.application_id == application.id))
    db.execute(delete(Fact).where(Fact.application_id == application.id, Fact.document_id.is_(None)))
    seen, app_drafts = set(), []
    for d in ratio_drafts + list(getattr(ctx, "derived_facts", []) or []):
        if id(d) not in seen:
            seen.add(id(d))
            app_drafts.append(d)
    ratio_rows, remap = persist_facts(db, app_drafts, application_id=application.id,
                                      borrower_id=application.borrower_id)
    for f in findings:
        f.evidence = [remap.get(k, k) for k in (f.evidence or [])]
        row = _finding_row(f, application_id=application.id)
        if (row.rule_id, row.title) in previous:   # keep the officer's resolution (H2)
            row.state, row.state_note = previous[(row.rule_id, row.title)]
        db.add(row)
    db.commit()

    st.start("narrative", 75)
    from app.modules.applications.narrative import generate_application_narrative
    generate_application_narrative(db, application, ctx, findings, ratio_drafts)

    if application.status == "processing":
        application.status = "in_review"
    application.analysed_at = utcnow()
    audit.record(db, None, "analyse", "application", application.uuid,
                 after={"documents": len(docs), "findings": len(findings), "ratios": len(ratio_rows)})
    db.commit()


def _fill_application_from_facts(db: Session, application, docs: list[Document]) -> None:
    """requested amount / term / rate come from the application form when not entered manually."""
    doc_ids = [d.id for d in docs if d.doc_type == "loan_application"]
    if not doc_ids:
        return
    facts = db.scalars(select(Fact).where(Fact.document_id.in_(doc_ids))).all()
    by_field = {f.field.split(".", 1)[-1]: f for f in facts if f.field.startswith("application.")}
    if application.requested_amount is None and "requested_amount" in by_field:
        application.requested_amount = float(by_field["requested_amount"].value)
    if application.term_months is None and "term_months" in by_field:
        application.term_months = int(round(float(by_field["term_months"].value)))
    if application.rate_pct is None and "rate_pct" in by_field:
        application.rate_pct = float(by_field["rate_pct"].value)
    db.flush()


def handle_narrative(db: Session, job: Job, st: Stages):
    """Regenerates only the narrative of an analysed application (e.g. after the LLM switch changed)."""
    from app.modules.applications.models import Application
    from app.modules.applications.narrative import generate_application_narrative
    from app.modules.applications.service import build_app_context, linked_documents

    application = db.scalars(select(Application).where(Application.uuid == UUID(job.payload["application_uuid"]))).first()
    if application is None:
        raise RuntimeError("application not found")
    AppContext = pipeline_fn("app.pipeline.rules", "AppContext")
    st.start("narrative", 30)
    docs = linked_documents(db, application)
    ctx = build_app_context(db, application, docs, AppContext, make)
    from app.modules.reconcile.models import Finding
    from app.pipeline.types import FindingDraft
    findings = [FindingDraft(rule_id=f.rule_id, severity=f.severity, label=f.label, title=f.title, detail=f.detail,
                             evidence=list(f.evidence or []), params=dict(f.params or {}))
                for f in db.scalars(select(Finding).where(Finding.application_id == application.id)).all()]
    ratio_drafts = [fact_to_draft(f) for f in db.scalars(select(Fact).where(
        Fact.application_id == application.id, Fact.kind == "computed")).all()]
    try:
        setattr(ctx, "findings", findings)
    except Exception:
        pass
    generate_application_narrative(db, application, ctx, findings, ratio_drafts)
    db.commit()


# ---------------------------------------------------------------------------------------- monitoring_run

def handle_monitoring_run(db: Session, job: Job, st: Stages):
    from app.modules.monitoring.service import run_monitoring
    run_monitoring(db, job, st)


def handle_borrower_narrative(db: Session, job: Job, st: Stages):
    from app.modules.llm.borrower import generate_borrower_narrative
    st.start("narrative", 20)
    generate_borrower_narrative(db, int(job.payload["borrower_id"]), int(job.payload["run_id"]))
    db.commit()


HANDLERS = {
    "analyse_document": handle_analyse_document,
    "analyse_application": handle_analyse_application,
    "narrative": handle_narrative,
    "monitoring_run": handle_monitoring_run,
    "borrower_narrative": handle_borrower_narrative,
}


def enqueue_job(db: Session, kind: str, payload: dict, ref: str, **kw) -> Job:
    return JobService(db).enqueue(kind, payload, ref=ref, **kw)
