"""View model for GET /applications/{number}/review (docs/plan/09-API.md).

Everything here is assembled from stored facts, findings and narrative runs; numbers on screen are fact
`display` strings, and every figure cell is a fact key the evidence pane can open.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.formatting import kuzs_to_mln
from app.core.timeutil import utcnow, working_days_between
from app.modules.applications.models import Application, Decision
from app.modules.applications.service import (REQUIRED_DOCS, annuity_installment, linked_documents,
                                              present_required)
from app.modules.audit.models import AuditLog
from app.modules.borrowers.models import Borrower
from app.modules.documents.models import Document
from app.modules.documents.periods import label_end, pretty
from app.modules.extraction.models import Fact
from app.modules.extraction.service import FactSerializer
from app.modules.llm.models import NarrativeRun
from app.modules.reconcile.models import Finding
from app.modules.reviews.models import FactReview
from app.modules.users.models import User

SLA_DAYS = 5
DISCLAIMER = ("Illustrative indicator derived from the extracted figures and rules shown. Not a validated credit "
              "score; does not replace the officer's assessment.")
INDICATOR_RULE = ("Based on the estimated debt service coverage for the new loan: ≥ 1.25 adequate, 1.00–1.25 tight, "
                  "< 1.00 insufficient. Unresolved issues are listed, not scored.")

FIGURE_ROWS = [  # (default label, form, line code, indent)
    ("Net revenue", "form2", "010", False),
    ("Cost of sales", "form2", "020", False),
    ("Operating expenses", "form2", "040", False),
    ("Net profit", "form2", "270", False),
    ("Total assets", "form1", "400", False),
    ("Current assets", "form1", "390", False),
    ("of which inventory", "form1", "140", True),
    ("Current liabilities", "form1", "600", False),
    ("Long-term liabilities", "form1", "490", False),
]
FLAG_BY_RULE = {"R06": "Contradicts statement", "R01": "Does not balance", "R09": "STIR mismatch"}
DOC_TITLES = {"form1": "Form 1 — Balance sheet", "form2": "Form 2 — Income statement",
              "bank_statement": "Bank statement", "loan_application": "Loan application form",
              "tax_declaration": "Tax declaration", "invoice": "Invoice", "sales_ledger": "Sales ledger"}
_NUM_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}


def _form_of(f: Fact, docs: dict[int, Document]) -> str:
    d = docs.get(f.document_id)
    if d is not None and d.doc_type in ("form1", "form2"):
        return d.doc_type
    return f.field.split(".", 1)[0]


def _choose_columns(form_facts: list[Fact]) -> list[dict]:
    """Two columns keyed by period END date, so a Form 2 flow (FY2025, H1-2026) and a Form 1 balance point
    (2025-12-31, 2026-06-30) land in the same column: the latest year end, then the latest period after it."""
    by_end: dict = {}
    for f in form_facts:
        end = label_end(f.period_label or "")
        if end is None:
            continue
        flow = not f.period_label[:1].isdigit()
        cur = by_end.get(end)
        if cur is None or (flow and not cur[1]):
            by_end[end] = (f.period_label, flow)
    ends = sorted(by_end)
    year_ends = [e for e in ends if e.month == 12 and e.day == 31]
    chosen = []
    if year_ends:
        chosen.append(year_ends[-1])
        later = [e for e in ends if e > year_ends[-1]]
        if later:
            chosen.append(later[-1])
    for e in reversed(ends):
        if len(chosen) >= 2:
            break
        if e not in chosen:
            chosen.append(e)
    cols = []
    for e in sorted(chosen):
        label, flow = by_end[e]
        key = label.lower().replace("-", "_") if flow else f"d{e.isoformat().replace('-', '_')}"
        cols.append({"key": key, "label": pretty(label), "end": e})
    return cols


def _pick(cands: list[Fact], end, docs: dict[int, Document]) -> Fact | None:
    """Among facts for this period end, prefer the document whose own period ends there (its current column)."""
    cands = [f for f in cands if label_end(f.period_label or "") == end]
    if not cands:
        return None

    def score(f: Fact):
        d = docs.get(f.document_id)
        primary = d is not None and d.period_end is not None and d.period_end == end
        return (primary, f.status in ("verified", "corrected"), f.confidence)
    return max(cands, key=score)


def _num_word(n: int) -> str:
    return _NUM_WORDS.get(n, str(n))


def build_review(db: Session, app: Application) -> dict:
    borrower = db.get(Borrower, app.borrower_id)
    docs_list = linked_documents(db, app)
    docs = {d.id: d for d in docs_list}
    doc_facts = list(db.scalars(select(Fact).where(Fact.document_id.in_(list(docs) or [-1])).order_by(Fact.id)).all())
    computed = list(db.scalars(select(Fact).where(Fact.application_id == app.id, Fact.document_id.is_(None))
                               .order_by(Fact.id)).all())
    findings = list(db.scalars(select(Finding).where(Finding.application_id == app.id).order_by(Finding.id)).all())
    sev_order = {"attn": 0, "watch": 1, "neutral": 2, "info": 3}
    findings.sort(key=lambda f: (f.state != "open", sev_order.get(f.severity, 9), f.id))

    # ---- figures table
    form_facts = [f for f in doc_facts if _form_of(f, docs) in ("form1", "form2") and f.line_code]
    columns = _choose_columns(form_facts)
    cited_by_rule: dict[str, str] = {}
    for fd in findings:
        if fd.state == "open" and fd.rule_id in FLAG_BY_RULE:
            for k in fd.evidence or []:
                cited_by_rule.setdefault(k, FLAG_BY_RULE[fd.rule_id])
    figures = []
    for default_label, form, code, indent in FIGURE_ROWS:
        cands = [f for f in form_facts if f.line_code == code and _form_of(f, docs) == form]
        if not cands:
            continue
        cells, confs, flag = {}, [], None
        for col in columns:
            fact = _pick(cands, col["end"], docs)
            cells[col["key"]] = fact.key if fact else None
            if fact:
                confs.append(fact.confidence)
                flag = flag or cited_by_rule.get(fact.key)
        label = default_label if indent else (_base_label(cands[0].label) or default_label)
        figures.append({"label": label, "indent": indent, "cells": cells,
                        "source": f"Form {form[-1]}, line {code}",
                        "confidence": round(min(confs) * 100) if confs else None, "flag": flag})
    inflow = [f for f in doc_facts if "inflow" in f.field and "avg" in f.field] or \
             [f for f in doc_facts if f.field.startswith("statement.") and "avg" in f.field and f.unit in ("kUZS", "UZS")]
    if inflow and columns:
        f = max(inflow, key=lambda x: x.id)
        d = docs.get(f.document_id)
        span = ""
        if d is not None and d.period_start and d.period_end:
            span = f", {d.period_start.strftime('%b')}–{d.period_end.strftime('%b %Y')}"
        figures.append({"label": "Avg monthly inflows (bank)", "indent": False,
                        "cells": {**{c["key"]: None for c in columns}, columns[-1]["key"]: f.key},
                        "source": f"Statement{span}", "confidence": round(f.confidence * 100), "flag": None})

    # ---- ratios
    ratio_facts = _latest_per_field([f for f in computed if f.field.startswith("ratio.")])
    ser = FactSerializer(db)
    all_facts = ser.by_key(doc_facts + computed)
    ratios = _ratio_boxes(ratio_facts, all_facts, findings)
    indicator = _indicator(ratio_facts, all_facts, findings)

    # ---- request
    amount = float(app.requested_amount) if app.requested_amount is not None else None
    installment = annuity_installment(amount, app.term_months, float(app.rate_pct) if app.rate_pct else None)
    inst_fact = next((f for f in computed if "installment" in f.field and f.unit in ("kUZS", "UZS")), None)
    # the uploaded loan form wins in the ratios; say so when it disagrees with the request entered online
    form_amt = next((f for f in doc_facts if f.field == "application.requested_amount"), None)
    form_term = next((f for f in doc_facts if f.field == "application.term_months"), None)
    request_mismatch = None
    if form_amt is not None and amount and abs(float(form_amt.value) - amount) > 0.01 * amount:
        request_mismatch = {"form_amount_display": kuzs_to_mln(float(form_amt.value)),
                            "form_term_months": int(form_term.value) if form_term is not None else None,
                            "form_amount_key": form_amt.key}

    # ---- documents
    present = present_required(docs_list)
    documents = [_doc_row(d) for d in docs_list]
    for (doc_type, title), ok in zip(REQUIRED_DOCS, present):
        if not ok:
            documents.append({"title": title, "filename": None, "uuid": None, "status": "missing",
                              "note": "Not provided"})

    narrative = _narrative(db, app_id=app.id)
    today = utcnow().date()
    return {
        "application": {"uuid": str(app.uuid), "number": app.number, "status": app.status,
                        "sla_day": working_days_between(app.received_on, today), "sla_days": SLA_DAYS,
                        "received_on": app.received_on.isoformat(),
                        "analysed_at": app.analysed_at.isoformat() if app.analysed_at else None},
        "applicant": {"name": borrower.name if borrower else "", "industry": borrower.industry if borrower else "",
                      "region": borrower.region if borrower else "",
                      "stir": _fmt_stir(borrower.stir) if borrower else "",
                      "since": borrower.since if borrower else None,
                      "employees": borrower.employees if borrower else None},
        "request": {"amount_display": kuzs_to_mln(amount) if amount is not None else "n/a",
                    "amount_unit": "mln UZS", "term_months": app.term_months,
                    "rate_pct": float(app.rate_pct) if app.rate_pct is not None else None,
                    "installment_display": (all_facts[inst_fact.key]["display"] if inst_fact else
                                            (kuzs_to_mln(installment) if installment is not None else "n/a")),
                    "installment_key": inst_fact.key if inst_fact else None,
                    "mismatch": request_mismatch,
                    "purpose": app.purpose, "collateral": app.collateral},
        "columns": [{"key": c["key"], "label": c["label"]} for c in columns],
        "issues": [_finding_out(f) for f in findings if f.severity in ("attn", "watch", "neutral")],
        "findings": [_finding_out(f) for f in findings],
        "figures": figures,
        "ratios": ratios,
        "indicator": indicator,
        "narrative": narrative,
        "documents": documents,
        "review_trail": _trail(db, app, docs_list),
        "decisions": _decisions(db, app),
        "facts": all_facts,
    }


def _decisions(db: Session, app: Application) -> list[dict]:
    """Officer decisions on this file, newest first (the applicant reads the reasoning as the bank's message)."""
    out = []
    for dec in db.scalars(select(Decision).where(Decision.application_id == app.id).order_by(Decision.id.desc())).all():
        u = db.get(User, dec.officer_id) if dec.officer_id else None
        out.append({"outcome": dec.outcome, "reasoning": dec.reasoning, "officer": u.full_name if u else "",
                    "created_at": dec.created_at.isoformat() if dec.created_at else None})
    return out


def _fmt_stir(stir: str) -> str:
    return f"{stir[:3]} {stir[3:6]} {stir[6:]}" if stir and len(stir) == 9 else stir or ""


def _finding_out(f: Finding) -> dict:
    return {"uuid": str(f.uuid), "rule_id": f.rule_id, "severity": f.severity, "label": f.label, "title": f.title,
            "detail": f.detail, "evidence": list(f.evidence or []), "state": f.state, "state_note": f.state_note}


def _is(field: str, *needles: str) -> bool:
    return all(n in field for n in needles)


def _base_label(label: str) -> str:
    """'Net revenue' from 'Net revenue' / 'Current ratio, 31 Dec 2025' → 'Current ratio'."""
    return (label or "").split(",")[0].strip()


RATIO_ORDER = ["ratio.current_ratio", "ratio.quick_ratio", "ratio.net_margin", "ratio.debt_to_equity", "dscr",
               "ratio.receivable_days", "ratio.installment_vs_revenue"]
HIDDEN_RATIOS = {"ratio.debt_service_capacity_monthly"}   # numerator of DSCR; still citable through its inputs


def _latest_per_field(facts: list[Fact]) -> list[Fact]:
    best: dict[str, Fact] = {}
    for f in facts:
        cur = best.get(f.field)
        end = label_end(f.period_label or "")
        if cur is None or (end and (label_end(cur.period_label or "") or end) <= end):
            best[f.field] = f

    def order(f: Fact):
        for i, key in enumerate(RATIO_ORDER):
            if key in f.field:
                return i
        return len(RATIO_ORDER)
    return sorted((f for f in best.values() if f.field not in HIDDEN_RATIOS), key=lambda f: (order(f), f.field))


def _dscr_pair(ratio_facts: list[Fact]) -> tuple[Fact | None, Fact | None]:
    dscr = [f for f in ratio_facts if "dscr" in f.field]
    new = next((f for f in dscr if "undeclared" not in f.field and "incl" not in f.field), None)
    incl = next((f for f in dscr if f is not new), None)
    return new, incl


def _ratio_boxes(ratio_facts: list[Fact], facts: dict, findings: list[Finding]) -> list[dict]:
    cited = {k for fd in findings if fd.state == "open" for k in (fd.evidence or [])}
    dscr_new, dscr_all = _dscr_pair(ratio_facts)
    boxes = []
    for f in ratio_facts:
        if f is dscr_all and dscr_new is not None:
            continue
        if f is dscr_new and dscr_all is not None:
            a, b = facts[dscr_new.key], facts[dscr_all.key]
            boxes.append({"label": "Est. debt service coverage", "value_display": f"{a['display']} → {b['display']}",
                          "note": f"New loan only → {_base_label(dscr_all.label).lower() or 'incl. undeclared'}",
                          "period": pretty(f.period_label or ""),
                          "flag": float(dscr_all.value) < float(dscr_new.value) or dscr_all.key in cited,
                          "fact_key": dscr_new.key, "fact_keys": [dscr_new.key, dscr_all.key]})
            continue
        d = facts[f.key]
        value = d["display"] + (" " + d["display_unit"] if f.unit == "days" and d["display_unit"] else "")
        boxes.append({"label": _base_label(f.label) or f.label, "value_display": value, "note": f.note or "",
                      "period": pretty(f.period_label or ""), "flag": f.key in cited,
                      "fact_key": f.key, "fact_keys": [f.key]})
    return boxes


def _indicator(ratio_facts: list[Fact], facts: dict, findings: list[Finding]) -> dict:
    open_issues = [f for f in findings if f.state == "open" and f.severity in ("attn", "watch")]
    dscr_new, dscr_all = _dscr_pair(ratio_facts)
    supports, against = [], []
    if dscr_new is None:
        label = "Not enough data for a repayment-capacity indicator"
    else:
        v = float(dscr_new.value)
        label = "Adequate" if v >= 1.25 else ("Tight" if v >= 1.0 else "Insufficient")
        if open_issues:
            n = len(open_issues)
            label += f", with {_num_word(n)} unresolved issue{'s' if n != 1 else ''}"
    for f in ratio_facts:
        d = facts[f.key]["display"]
        v = float(f.value)
        fld = f.field
        if f is dscr_new:
            (supports if v >= 1.25 else against).append(f"Est. debt service coverage {d} on the new loan alone")
        elif f is dscr_all:
            if v < 1.25:
                against.append(f"Coverage falls to {d} including repayments found in the bank statement")
        elif "current_ratio" in fld:
            (supports if v >= 1.2 else against).append(f"Current ratio {d}")
        elif "quick_ratio" in fld:
            (supports if v >= 1.0 else against).append(f"Quick ratio {d}" + (" — relies on inventory" if v < 1.0 else ""))
        elif "net_margin" in fld:
            (supports if v > 0 else against).append(f"Net margin {d}")
        elif "debt_to_equity" in fld:
            (supports if v <= 1.5 else against).append(f"Debt to equity {d} (declared liabilities)")
    seen = set()
    for f in open_issues:
        text = f"{f.label}: {f.title}"
        if text not in seen:
            seen.add(text)
            against.append(text)
    return {"label": label, "supports": supports, "weighs_against": against, "disclaimer": DISCLAIMER,
            "rule": INDICATOR_RULE}


def _narrative(db: Session, app_id: int | None = None, borrower_id: int | None = None) -> dict:
    stmt = select(NarrativeRun)
    stmt = stmt.where(NarrativeRun.application_id == app_id) if app_id else stmt.where(
        NarrativeRun.borrower_id == borrower_id)
    runs = list(db.scalars(stmt.order_by(NarrativeRun.generation.desc(), NarrativeRun.attempt.desc())).all())
    if not runs:
        return {"mode": None, "markdown": "", "accepted_at": None, "attempts": 0, "verified": False,
                "rejected": [], "llm_status": None, "llm_status_text": ""}
    latest_gen = runs[0].generation
    gen_runs = [r for r in runs if r.generation == latest_gen]
    chosen = next((r for r in gen_runs if r.accepted), None) or next((r for r in runs if r.accepted), None)
    rejected = [{"attempt": r.attempt, "mode": r.mode, "at": r.created_at.isoformat() if r.created_at else None,
                 "unmatched": (r.verifier_report or {}).get("unmatched", []),
                 "uncited_sentences": (r.verifier_report or {}).get("uncited_sentences", []),
                 "unknown_ids": (r.verifier_report or {}).get("unknown_ids", [])}
                for r in gen_runs if not r.accepted]
    tmpl = next((r for r in gen_runs if r.mode == "template"), None)
    rep = (tmpl.verifier_report or {}) if tmpl is not None else {}
    reason = {"llm_status": rep.get("llm_status"), "llm_status_text": rep.get("llm_status_text") or ""}
    if reason["llm_status"] == "ok":
        reason = {"llm_status": None, "llm_status_text": ""}   # LLM was reachable; drafts were rejected instead
    if chosen is None:
        return {"mode": gen_runs[0].mode, "markdown": "", "accepted_at": None,
                "attempts": len([r for r in gen_runs if r.mode == "llm"]), "verified": False, "rejected": rejected,
                **reason}
    if chosen.mode == "llm":
        reason = {"llm_status": "ok", "llm_status_text": ""}
    return {"mode": chosen.mode, "markdown": chosen.output,
            "accepted_at": chosen.created_at.isoformat() if chosen.created_at else None,
            "attempts": len([r for r in gen_runs if r.mode == "llm"]), "verified": True, "rejected": rejected,
            **reason}


def _doc_row(d: Document) -> dict:
    base = DOC_TITLES.get(d.doc_type, d.filename)
    period = ""
    if d.doc_type == "form1" and d.period_end:
        period = d.period_end.strftime("%d %b %Y").lstrip("0")
    elif d.doc_type in ("form2", "tax_declaration") and d.period_end:
        from app.modules.documents.periods import resolve_label
        period = pretty(resolve_label("", d.doc_type, d.period_start, d.period_end))
    elif d.doc_type == "bank_statement" and d.period_start and d.period_end:
        period = f"{d.period_start.strftime('%d.%m')}–{d.period_end.strftime('%d.%m.%Y')}"
    title = f"{base}, {period}" if period else base
    s = d.summary or {}
    notes = []
    if d.doc_type in ("form1", "form2"):
        if not d.text_layer:
            notes.append("scanned")
        low = int(s.get("low_confidence") or 0)
        if low:
            notes.append(f"{low} field{'s' if low != 1 else ''} < 80%")
    if d.doc_type == "bank_statement" and s.get("transactions") is not None:
        notes.append(f"{s['transactions']:,} transactions · {s.get('categories', 0)} categories".replace(",", " "))
    if d.failure_cause:
        notes.append(d.failure_cause)
    status = {"analyzed": "processed", "clarification": "needs clarification"}.get(d.status, d.status)
    return {"title": title, "filename": d.filename, "uuid": str(d.uuid), "doc_type": d.doc_type, "status": status,
            "note": " · ".join(notes)}


def _trail(db: Session, app: Application, docs: list[Document]) -> list[dict]:
    events: list[tuple] = []
    for r in db.scalars(select(NarrativeRun).where(NarrativeRun.application_id == app.id)).all():
        rep = r.verifier_report or {}
        if r.mode == "llm":
            text = (f"AI draft accepted by the verifier (attempt {r.attempt})" if r.accepted else
                    f"AI draft attempt {r.attempt} rejected by the verifier: "
                    f"{len(rep.get('unmatched', []))} unmatched number(s), "
                    f"{len(rep.get('uncited_sentences', []))} uncited sentence(s)")
        else:
            text = "Template summary generated from the facts (LLM off or drafts rejected)"
        events.append((r.created_at, text))
    users = {}
    fact_ids = [f.id for f in db.scalars(select(Fact).where(
        (Fact.document_id.in_([d.id for d in docs] or [-1])) | (Fact.application_id == app.id))).all()]
    if fact_ids:
        for rv in db.scalars(select(FactReview).where(FactReview.fact_id.in_(fact_ids))).all():
            u = users.get(rv.user_id) or (db.get(User, rv.user_id) if rv.user_id else None)
            users[rv.user_id] = u
            fact = db.get(Fact, rv.fact_id)
            verb = {"verify": "verified", "correct": "corrected", "flag": "flagged"}.get(rv.action, rv.action)
            events.append((rv.created_at, f"{u.full_name if u else 'Officer'} {verb} {fact.label} {pretty(fact.period_label)}".strip()))
    for dec in db.scalars(select(Decision).where(Decision.application_id == app.id)).all():
        u = db.get(User, dec.officer_id) if dec.officer_id else None
        events.append((dec.created_at, f"{u.full_name if u else 'Officer'} recorded the decision: " + {"recommend": "recommend approval", "decline": "recommend decline", "request_info": "request more information"}.get(dec.outcome, dec.outcome)))
    for a in db.scalars(select(AuditLog).where(AuditLog.entity == "application", AuditLog.entity_uuid == app.uuid)).all():
        if a.action == "analyse":
            n = (a.after or {}).get("documents")
            events.append((a.created_at, f"Analysis completed from {n} documents"))
        elif a.action == "create":
            events.append((a.created_at, "Application registered"))
    for a in db.scalars(select(AuditLog).where(AuditLog.entity == "finding", AuditLog.action == "update")).all():
        after = a.after or {}
        if after.get("application_uuid") == str(app.uuid):
            events.append((a.created_at, f"{a.actor_email} marked a finding {after.get('state')}"))
    events = [e for e in events if e[0] is not None]
    events.sort(key=lambda e: e[0])
    return [{"at": at.isoformat(), "text": text} for at, text in events]
