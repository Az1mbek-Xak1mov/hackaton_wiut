"""Monitoring runs (M01–M06 per borrower) and the portfolio read models built from the latest run."""
import importlib
import logging
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.formatting import fmt_number, kuzs_to_bn, kuzs_to_mln
from app.core.timeutil import aware, utcnow, working_days_between
from app.modules.applications.models import Application
from app.modules.borrowers.models import Borrower, Loan, Repayment
from app.modules.documents.models import Document
from app.modules.extraction.models import Fact
from app.modules.extraction.service import fact_to_draft, persist_facts
from app.modules.jobs.service import JobService
from app.modules.monitoring.models import MonitoringResult, MonitoringRun
from app.modules.reconcile.models import Finding
from app.modules.statements.models import Transaction

logger = logging.getLogger(__name__)

STATUS_META = [  # rule definitions shown next to the counts (disclosed thresholds; see 02-PIPELINE M01–M06)
    ("stable", "Stable", "No indicator moved beyond its threshold in the last 2 periods"),
    ("watch", "Watch", "One indicator moved; cause not yet confirmed, or data is late"),
    ("attn", "Attention", "Two or more indicators moved, or a payment was late"),
]
SEVERITY = {"attn": 0, "watch": 1, "stable": 2, "unknown": 3, "not_monitored": 4}
NOT_MONITORED = "not_monitored"
CALIBRATION_NOTE = "Illustrative thresholds; calibration against bank history is pilot month 1."
TERMINAL_DOC = {"analyzed", "clarification", "failed"}


def start_run(db: Session, actor, as_of: date | None = None, borrower_ids: list[int] | None = None):
    """Queues a monitoring run. `borrower_ids` restricts it (e.g. the seed's earlier-quarter run for borrowers
    that have earlier statements); None = the whole portfolio."""
    run = MonitoringRun(status="queued", as_of=as_of or utcnow().date(), thresholds={})
    db.add(run)
    db.flush()
    payload = {"run_uuid": str(run.uuid), "as_of": run.as_of.isoformat()}
    if borrower_ids:
        payload["borrower_ids"] = sorted(int(b) for b in borrower_ids)
    job = JobService(db).enqueue("monitoring_run", payload, ref=f"monitoring_run:{run.uuid}")
    from app.modules.audit import service as audit
    audit.record(db, actor, "create", "monitoring_run", run.uuid, after={"as_of": run.as_of.isoformat()})
    db.commit()
    db.refresh(run)
    db.refresh(job)
    return run, job


def _remap(obj, remap: dict):
    if not remap:
        return obj
    if isinstance(obj, str):
        return remap.get(obj, obj)
    if isinstance(obj, list):
        return [_remap(v, remap) for v in obj]
    if isinstance(obj, dict):
        return {k: _remap(v, remap) for k, v in obj.items()}
    return obj


def _loan_dict(loan: Loan, as_of: date) -> dict:
    nxt = None
    try:
        nxt = as_of.replace(day=loan.due_day)
        if nxt <= as_of:
            nxt = (nxt.replace(day=1) + timedelta(days=32)).replace(day=loan.due_day)
    except ValueError:
        nxt = None
    return {"contract_no": loan.contract_no, "original_amount": float(loan.original_amount),
            "outstanding": float(loan.outstanding), "installment": float(loan.installment), "due_day": loan.due_day,
            "term_months": loan.term_months, "paid_count": loan.paid_count, "disbursed_on": loan.disbursed_on,
            "maturity_on": loan.maturity_on, "next_due": nxt, "rate_pct": float(loan.rate_pct) if loan.rate_pct else None}


def run_monitoring(db: Session, job, st) -> None:
    from app.modules.jobs.runner import _finding_row, _jsonable, doc_context_dict, make, pipeline_fn
    from app.pipeline.types import TxnDraft

    evaluate_borrower = pipeline_fn("app.pipeline.monitoring", "evaluate_borrower")
    MonitoringContext = pipeline_fn("app.pipeline.monitoring", "MonitoringContext")
    mon = importlib.import_module("app.pipeline.monitoring")
    thresholds = dict(getattr(mon, "DEFAULT_THRESHOLDS", {}))
    disclosure = {"values": thresholds,
                  "rules": mon.threshold_disclosure(thresholds) if hasattr(mon, "threshold_disclosure") else [],
                  "note": getattr(mon, "CALIBRATION_LABEL", CALIBRATION_NOTE)}

    run = db.scalars(select(MonitoringRun).where(MonitoringRun.uuid == UUID(job.payload["run_uuid"]))).first()
    if run is None:
        raise RuntimeError("monitoring run not found")
    as_of = date.fromisoformat(job.payload.get("as_of")) if job.payload.get("as_of") else utcnow().date()
    run.status, run.started_at, run.as_of, run.thresholds = "running", utcnow(), as_of, _jsonable(disclosure)
    st.start("monitor", 2)

    borrower_ids = list(db.scalars(select(Loan.borrower_id).distinct()).all())
    if job.payload.get("borrower_ids"):
        wanted = set(job.payload["borrower_ids"])
        borrower_ids = [b for b in borrower_ids if b in wanted]
    borrowers = db.scalars(select(Borrower).where(Borrower.id.in_(borrower_ids)).order_by(Borrower.id)).all() \
        if borrower_ids else []
    n = max(1, len(borrowers))
    for i, b in enumerate(borrowers):
        try:
            with db.begin_nested():   # one borrower failing never loses the others
                loans = db.scalars(select(Loan).where(Loan.borrower_id == b.id).order_by(Loan.disbursed_on.desc())).all()
                loan = loans[0]
                # only what was known at `as_of`: installments due by then, documents covering periods up to then
                reps = db.scalars(select(Repayment).where(Repayment.loan_id == loan.id, Repayment.due_on <= as_of)
                                  .order_by(Repayment.n)).all()
                docs = db.scalars(select(Document).where(Document.borrower_id == b.id, Document.owner_kind != "public",
                                                         Document.status.in_(TERMINAL_DOC))
                                  .order_by(Document.id)).all()
                docs = [d for d in docs if d.period_end is None or d.period_end <= as_of]
                doc_ids = [d.id for d in docs] or [-1]
                facts = db.scalars(select(Fact).where(Fact.document_id.in_(doc_ids)).order_by(Fact.id)).all()
                txns = db.scalars(select(Transaction).where(Transaction.document_id.in_(doc_ids))
                                  .order_by(Transaction.booked_on)).all()
                repayments = [{"n": r.n, "due_on": r.due_on,
                               "paid_on": r.paid_on if r.paid_on and r.paid_on <= as_of else None,
                               "amount": float(r.amount) if r.amount is not None else None} for r in reps]
                ctx = make(MonitoringContext,
                           borrower={"id": b.id, "uuid": str(b.uuid), "name": b.name, "stir": b.stir,
                                     "industry": b.industry, "region": b.region},
                           loan=_loan_dict(loan, as_of) | {"repayments": repayments},
                           repayments=repayments,
                           facts=[fact_to_draft(f) for f in facts],
                           transactions=[TxnDraft(row_n=t.row_n, booked_on=t.booked_on, amount=float(t.amount),
                                                  counterparty=t.counterparty, counterparty_stir=t.counterparty_stir,
                                                  account=t.account, purpose=t.purpose, category=t.category,
                                                  category_source=t.category_source, category_conf=t.category_conf,
                                                  recurring_group=t.recurring_group) for t in txns],
                           documents=[doc_context_dict(d) for d in docs], as_of=as_of, thresholds=thresholds)
                res = evaluate_borrower(ctx) or {}
                rows, remap = persist_facts(db, res.get("facts") or [], borrower_id=b.id)
                for f in rows:
                    f.kind = f.kind or "computed"
                for fd in res.get("findings") or []:
                    fd.evidence = _remap(list(fd.evidence or []), remap)
                    db.add(_finding_row(fd, borrower_id=b.id, monitoring_run_id=run.id))
                prev = db.scalars(select(MonitoringResult).where(MonitoringResult.borrower_id == b.id,
                                                                 MonitoringResult.run_id != run.id)
                                  .order_by(MonitoringResult.id.desc())).first()
                db.add(MonitoringResult(run_id=run.id, borrower_id=b.id, status=str(res.get("status") or "watch")[:8],
                                        reason=str(res.get("reason") or "")[:255],
                                        indicators=_remap(_jsonable(res.get("indicators") or {}), remap),
                                        prev_status=prev.status if prev else None))
                db.flush()
        except Exception:
            logger.exception("monitoring failed for borrower %s", b.id)
        if i % 10 == 0:
            st.start("monitor", 2 + int(95 * (i + 1) / n))
    run.status, run.finished_at = "done", utcnow()
    # the AI explanation for every borrower under Watch/Attention, one job each (LLM, or the verified template)
    from app.modules.llm.borrower import borrowers_to_explain
    jobs = JobService(db)
    for bid in borrowers_to_explain(db, run):
        jobs.enqueue("borrower_narrative", {"borrower_id": bid, "run_id": run.id}, ref=f"borrower:{bid}")
    db.commit()


# ------------------------------------------------------------------------------------------- read models

def latest_run(db: Session) -> MonitoringRun | None:
    return db.scalars(select(MonitoringRun).where(MonitoringRun.status == "done")
                      .order_by(MonitoringRun.finished_at.desc(), MonitoringRun.id.desc())).first()


def _results(db: Session, run: MonitoringRun | None) -> dict[int, MonitoringResult]:
    if run is None:
        return {}
    return {r.borrower_id: r for r in db.scalars(select(MonitoringResult).where(MonitoringResult.run_id == run.id)).all()}


def _ind(res: MonitoringResult | None, code: str) -> dict:
    if res is None:
        return {}
    ind = (res.indicators or {}).get(code)
    return ind if isinstance(ind, dict) else {}


def _exposure(db: Session) -> dict[int, float]:
    return {bid: float(v or 0) for bid, v in db.execute(
        select(Loan.borrower_id, func.sum(Loan.outstanding)).group_by(Loan.borrower_id)).all()}


def _coverage_display(res: MonitoringResult | None) -> str:
    ind = _ind(res, "M04")
    if ind.get("display"):
        return str(ind["display"])
    v = ind.get("value")
    return f"{fmt_number(float(v), 1)}×" if isinstance(v, (int, float)) else "n/a"


def _latest_periods(db: Session, borrower_ids: list[int]) -> dict[int, str]:
    """Latest reporting period per borrower, in one query."""
    from app.modules.documents.periods import pretty, resolve_label
    latest: dict[int, tuple] = {}
    rows = db.execute(select(Document.borrower_id, Document.doc_type, Document.period_start, Document.period_end)
                      .where(Document.borrower_id.in_(borrower_ids or [-1]), Document.period_end.is_not(None),
                             Document.owner_kind != "public")).all()
    for bid, doc_type, start, end in rows:
        if bid not in latest or end > latest[bid][2]:
            latest[bid] = (doc_type, start, end)
    return {bid: pretty(resolve_label("", t, start, end)) for bid, (t, start, end) in latest.items()}


def borrower_items(db: Session, status: str | None = None) -> dict:
    run = latest_run(db)
    results = _results(db, run)
    exposure = _exposure(db)
    loans = {}
    for loan in db.scalars(select(Loan).order_by(Loan.disbursed_on.desc())).all():
        loans.setdefault(loan.borrower_id, loan)
    borrowers = db.scalars(select(Borrower)).all()   # incl. businesses without a loan (e.g. online applicants)
    periods = _latest_periods(db, [b.id for b in borrowers])
    items = []
    for b in borrowers:
        res = results.get(b.id)
        loan = loans.get(b.id)
        st = res.status if res else ("unknown" if loan else NOT_MONITORED)
        reason = res.reason if res else ("Not yet monitored" if loan else "Not monitored — no loan with the bank")
        trend = _ind(res, "M01").get("value")
        items.append({
            "uuid": str(b.uuid), "loan_id": loan.contract_no if loan else None, "name": b.name, "industry": b.industry,
            "region": b.region, "outstanding": exposure.get(b.id, 0.0),
            "outstanding_display": kuzs_to_mln(exposure.get(b.id, 0.0)),
            "trend_pct": float(trend) if isinstance(trend, (int, float)) else None,
            "trend_display": (_ind(res, "M01").get("display") or
                              (f"{'+' if trend > 0 else ''}{fmt_number(float(trend), 1)}%"
                               if isinstance(trend, (int, float)) else "n/a")),
            "coverage_display": _coverage_display(res), "latest_period": periods.get(b.id, "n/a"),
            "status": st, "reason": reason,
            "updated": (run.finished_at.date().isoformat() if run and run.finished_at else None),
        })
    counts = {"all": len(items), "stable": 0, "watch": 0, "attn": 0, NOT_MONITORED: 0}
    for it in items:
        if it["status"] in counts:
            counts[it["status"]] += 1
    items.sort(key=lambda it: (SEVERITY.get(it["status"], 3), -it["outstanding"]))
    if status:
        items = [it for it in items if it["status"] == status]
    return {"counts": counts, "items": items, "run": _run_out(run), "calibration_note": CALIBRATION_NOTE,
            "thresholds": run.thresholds if run else {}}


def _run_out(run: MonitoringRun | None) -> dict | None:
    if run is None:
        return None
    return {"uuid": str(run.uuid), "status": run.status, "as_of": run.as_of.isoformat() if run.as_of else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None}


def portfolio_summary(db: Session) -> dict:
    run = latest_run(db)
    results = _results(db, run)
    exposure = _exposure(db)
    total_exposure = sum(exposure.values())
    monitored = len(exposure)
    dist = []
    for code, label, means in STATUS_META:
        ids = [bid for bid, r in results.items() if r.status == code]
        exp = sum(exposure.get(bid, 0.0) for bid in ids)
        dist.append({"status": code, "label": label, "means": means, "n": len(ids),
                     "exposure_display": kuzs_to_bn(exp), "exposure_unit": "bn UZS",
                     "pct": round(100.0 * exp / total_exposure, 1) if total_exposure else 0.0})
    attn = next(d for d in dist if d["status"] == "attn")

    today = utcnow().date()
    apps = db.scalars(select(Application).where(Application.status.in_(
        ("processing", "in_review", "waiting_on_applicant"))).order_by(Application.received_on)).all()
    names = {b.id: b.name for b in db.scalars(select(Borrower)).all()}
    beyond = [a for a in apps if working_days_between(a.received_on, today) > 5]

    queue = []
    open_counts = dict(db.execute(select(Finding.application_id, func.count(Finding.id))
                                  .where(Finding.state == "open", Finding.application_id.is_not(None),
                                         Finding.severity.in_(("attn", "watch", "neutral")))
                                  .group_by(Finding.application_id)).all())
    for a in apps:
        n = open_counts.get(a.id, 0)
        day = working_days_between(a.received_on, today)
        queue.append({"kind": "application", "ref": a.number, "name": names.get(a.borrower_id, ""),
                      "reason": (f"{n} issue{'s' if n != 1 else ''} to resolve · day {day} of 5" if n
                                 else f"{a.status.replace('_', ' ')} · day {day} of 5"),
                      "severity": "info", "action": "Review"})
    loans = {}
    for loan in db.scalars(select(Loan).order_by(Loan.disbursed_on.desc())).all():
        loans.setdefault(loan.borrower_id, loan)
    flagged = sorted([r for r in results.values() if r.status in ("attn", "watch")],
                     key=lambda r: (SEVERITY[r.status], -exposure.get(r.borrower_id, 0.0)))
    for r in flagged:
        loan = loans.get(r.borrower_id)
        queue.append({"kind": "borrower", "ref": loan.contract_no if loan else "", "name": names.get(r.borrower_id, ""),
                      "reason": r.reason, "severity": r.status, "action": "Open"})

    changes = []
    if run is not None:
        since = (aware(run.finished_at) or utcnow()) - timedelta(days=7)
        recent = db.scalars(select(MonitoringResult).join(MonitoringRun, MonitoringRun.id == MonitoringResult.run_id)
                            .where(MonitoringRun.status == "done", MonitoringRun.finished_at >= since,
                                   MonitoringResult.prev_status.is_not(None),
                                   MonitoringResult.prev_status != MonitoringResult.status)
                            .order_by(MonitoringResult.id.desc())).all()
        seen = set()
        for r in recent:
            if r.borrower_id in seen:
                continue
            seen.add(r.borrower_id)
            rrun = db.get(MonitoringRun, r.run_id)
            changes.append({"borrower_uuid": None, "loan_id": loans[r.borrower_id].contract_no if r.borrower_id in loans else None,
                            "name": names.get(r.borrower_id, ""),
                            "outstanding_display": kuzs_to_mln(exposure.get(r.borrower_id, 0.0)),
                            "from": r.prev_status, "to": r.status,
                            "date": rrun.finished_at.date().isoformat() if rrun and rrun.finished_at else None,
                            "reason": r.reason})

    trend = []
    for rr in db.scalars(select(MonitoringRun).where(MonitoringRun.status == "done").order_by(MonitoringRun.as_of)).all():
        res = db.scalars(select(MonitoringResult).where(MonitoringResult.run_id == rr.id)).all()
        trend.append({"as_of": rr.as_of.isoformat() if rr.as_of else None,
                      "watch_plus_attn": sum(1 for r in res if r.status in ("watch", "attn"))})

    return {
        "as_of": run.as_of.isoformat() if run and run.as_of else None,
        "run": _run_out(run),
        "monitored": monitored,
        "exposure_display": kuzs_to_bn(total_exposure), "exposure_unit": "bn UZS",
        "applications_awaiting": len(apps), "beyond_target": len(beyond),
        "requested_display": kuzs_to_bn(sum(float(a.requested_amount or 0) for a in apps)),
        "warning": {"n": attn["n"], "exposure_display": attn["exposure_display"], "pct": attn["pct"]},
        "status_distribution": dist,
        "thresholds": run.thresholds if run else {},
        "calibration_note": CALIBRATION_NOTE,
        "queue": queue,
        "status_changes": changes,
        "trend": trend,
    }


def borrower_detail(db: Session, loan: Loan | None, borrower: Borrower | None = None) -> dict:
    from app.modules.applications.review import _finding_out, _narrative
    from app.modules.documents.periods import label_end, pretty
    from app.modules.extraction.service import FactSerializer

    b = borrower or db.get(Borrower, loan.borrower_id)
    run = latest_run(db)
    res_all = db.scalars(select(MonitoringResult).where(MonitoringResult.borrower_id == b.id)
                         .order_by(MonitoringResult.id)).all()
    current = res_all[-1] if res_all else None
    reps = db.scalars(select(Repayment).where(Repayment.loan_id == loan.id).order_by(Repayment.n)).all() if loan else []
    docs = db.scalars(select(Document).where(Document.borrower_id == b.id, Document.owner_kind != "public")
                      .order_by(Document.id.desc())).all()
    doc_facts = db.scalars(select(Fact).where(Fact.document_id.in_([d.id for d in docs] or [-1]))).all()
    own_facts = db.scalars(select(Fact).where(Fact.borrower_id == b.id, Fact.document_id.is_(None))).all()
    alerts = []
    if current is not None:
        alerts = db.scalars(select(Finding).where(Finding.borrower_id == b.id,
                                                  Finding.monitoring_run_id == current.run_id)
                            .order_by(Finding.id)).all()

    # status history: compress consecutive equal statuses
    history = []
    for r in res_all:
        rr = db.get(MonitoringRun, r.run_id)
        when = rr.finished_at.date().isoformat() if rr and rr.finished_at else None
        if not history or history[-1]["status"] != r.status:
            history.append({"status": r.status, "from": when})
    since = history[-1]["from"] if history else None

    # quarterly / period series from statutory facts (each point is a fact key)
    series_fields = {"revenue": ("form2", "010"), "opex": ("form2", "040"), "net_profit": ("form2", "270"),
                     "receivables_end": ("form1", None)}
    periods = sorted({f.period_label for f in doc_facts if label_end(f.period_label or "") and f.line_code},
                     key=label_end)[-4:]
    series = {"periods": [pretty(p) for p in periods], "period_labels": periods}
    for name, (form, code) in series_fields.items():
        if code is None:
            continue
        row = []
        for p in periods:
            cands = [f for f in doc_facts if f.line_code == code and f.field.startswith(form) and f.period_label == p]
            row.append(max(cands, key=lambda f: f.confidence).key if cands else None)
        series[name] = row

    today = utcnow().date()
    strip = [{"n": r.n, "due_on": r.due_on.isoformat(), "paid_on": r.paid_on.isoformat() if r.paid_on else None,
              "state": ("late" if r.paid_on and r.paid_on > r.due_on else "on_time" if r.paid_on else
                        ("overdue" if r.due_on < today else "upcoming")),
              "days_late": (r.paid_on - r.due_on).days if r.paid_on and r.paid_on > r.due_on else 0} for r in reps]

    timeline = []
    for h in history:
        timeline.append({"date": h["from"], "title": f"Status → {h['status'].replace('attn', 'Attention').title()}",
                         "status": h["status"]})
    for r in strip:
        if r["state"] == "late":
            timeline.append({"date": r["paid_on"], "title": f"Installment {r['n']} paid {r['days_late']} days late",
                             "status": "attn"})
    for d in docs:
        timeline.append({"date": d.created_at.date().isoformat() if d.created_at else None,
                         "title": f"Uploaded: {d.filename}", "status": "neutral"})
    timeline = sorted([t for t in timeline if t["date"]], key=lambda t: t["date"])

    ser = FactSerializer(db)
    facts = ser.by_key(list(doc_facts) + list(own_facts))
    return {
        "business": {"uuid": str(b.uuid), "name": b.name, "industry": b.industry, "region": b.region,
                     "stir": b.stir, "since": b.since, "employees": b.employees},
        "loan": ({"loan_id": loan.contract_no, "type": loan.loan_type, "purpose": loan.purpose,
                  "disbursed_on": loan.disbursed_on.isoformat(),
                  "original_display": kuzs_to_mln(loan.original_amount),
                  "outstanding_display": kuzs_to_mln(loan.outstanding),
                  "installment_display": kuzs_to_mln(loan.installment), "due_day": loan.due_day,
                  "term_months": loan.term_months, "paid": sum(1 for r in strip if r["paid_on"]),
                  "left": loan.term_months - sum(1 for r in strip if r["paid_on"]),
                  "maturity_on": loan.maturity_on.isoformat() if loan.maturity_on else None,
                  "collateral": loan.collateral, "coverage_display": _coverage_display(current),
                  "repayments": strip, "unit": "mln UZS"} if loan else None),
        "status": {"current": current.status if current else ("unknown" if loan else NOT_MONITORED), "since": since, "history": history,
                   "reason": current.reason if current else "", "indicators": current.indicators if current else {}},
        "alerts": [_finding_out(f) | {"date": f.created_at.date().isoformat() if f.created_at else None}
                   for f in alerts],
        "quarterly": series,
        "narrative": _narrative(db, borrower_id=b.id),
        "timeline": timeline,
        "documents": [{"uuid": str(d.uuid), "filename": d.filename, "doc_type": d.doc_type, "status": d.status,
                       "uploaded": d.created_at.date().isoformat() if d.created_at else None,
                       "note": (f"{(d.summary or {}).get('transactions')} transactions"
                                if (d.summary or {}).get("transactions") is not None else "")} for d in docs],
        "run": _run_out(run),
        "calibration_note": CALIBRATION_NOTE,
        "facts": facts,
    }
