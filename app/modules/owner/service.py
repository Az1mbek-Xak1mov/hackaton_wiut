"""Owner dashboard: the business's own figures, read from facts the pipeline already produced.

Nothing here computes a new number. Monthly money in / out and month-end balances are the statement
aggregate facts written by `app/pipeline/statements/normalise.py`; revenue and net profit are Form 2 facts;
ratios are the `ratio.*` facts `app/pipeline/ratios.py` computed for the owner's applications. Every value
is returned as the serialized fact, so the UI can say which document (and page) it came from.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.applications.models import Application
from app.modules.borrowers.models import Borrower
from app.modules.documents.models import Document
from app.modules.documents.periods import label_end, pretty
from app.modules.extraction.models import Fact
from app.modules.extraction.service import FactSerializer

MONTHS_SHOWN = 12
PERIODS_SHOWN = 6

# ratio field → plain-language name and what it means (display only; values are the computed facts)
RATIO_NAMES = [
    ("ratio.net_margin", "Profit kept from each 100 so'm of sales",
     "Net profit divided by revenue, from Form 2."),
    ("ratio.current_ratio", "Short-term assets for each 1 so'm of short-term debts",
     "Current assets divided by current liabilities, from Form 1. Above 1 means short-term debts are covered."),
    ("ratio.debt_to_equity", "Debts for each 1 so'm of your own capital",
     "Liabilities divided by equity, from Form 1."),
    ("ratio.receivable_days", "Days customers take to pay you",
     "Receivables divided by revenue, times the days in the period."),
]


def _best(facts: list[Fact]) -> Fact | None:
    # one figure per slot: the most confident, then the most recently stored
    return max(facts, key=lambda f: (f.confidence or 0, f.id)) if facts else None


def owner_dashboard(db: Session, borrower: Borrower) -> dict:
    docs = db.scalars(select(Document).where(Document.borrower_id == borrower.id,
                                             Document.owner_kind != "public")).all()
    doc_ids = [d.id for d in docs] or [-1]
    facts = list(db.scalars(select(Fact).where(Fact.document_id.in_(doc_ids))).all())

    # --- bank statements: monthly money in / out and month-end balance
    by_month: dict[str, dict[str, list[Fact]]] = {}
    for f in facts:
        for kind, prefix in (("money_in", "statement.inflow.total."), ("money_out", "statement.outflow.total."),
                             ("balance_end", "statement.balance_end.")):
            if f.field.startswith(prefix):
                ym = f.field[len(prefix):]
                if len(ym) == 7 and ym[:4].isdigit():
                    by_month.setdefault(ym, {}).setdefault(kind, []).append(f)
    months = sorted(by_month)[-MONTHS_SHOWN:]
    chosen: list[Fact] = []
    month_rows = []
    for ym in months:
        row = {"month": ym}
        for kind in ("money_in", "money_out", "balance_end"):
            f = _best(by_month[ym].get(kind, []))
            row[kind] = f.key if f else None
            if f:
                chosen.append(f)
        month_rows.append(row)
    cash = next((r["balance_end"] for r in reversed(month_rows) if r["balance_end"]), None)

    # --- Form 2: revenue and net profit per reported period
    codes = {"revenue": "010", "net_profit": "270"}
    stat = [f for f in facts if f.field.startswith("form2") and f.line_code in codes.values()
            and label_end(f.period_label or "")]
    periods = sorted({f.period_label for f in stat}, key=label_end)[-PERIODS_SHOWN:]
    period_rows = []
    for p in periods:
        row = {"period": p, "label": pretty(p)}
        for name, code in codes.items():
            f = _best([x for x in stat if x.line_code == code and x.period_label == p])
            row[name] = f.key if f else None
            if f:
                chosen.append(f)
        period_rows.append(row)

    # --- ratios computed for the owner's applications (latest period per ratio)
    apps = db.scalars(select(Application.id).where(Application.borrower_id == borrower.id)).all()
    rfacts = list(db.scalars(select(Fact).where(Fact.application_id.in_(list(apps) or [-1]),
                                                Fact.document_id.is_(None),
                                                Fact.field.startswith("ratio."))).all())
    ratios = []
    for field, name, explain in RATIO_NAMES:
        cands = [f for f in rfacts if f.field == field]
        f = max(cands, key=lambda x: (label_end(x.period_label or "") or label_end("1900-01-01"), x.id)) \
            if cands else None
        if f:
            chosen.append(f)
        ratios.append({"field": field, "name": name, "explain": explain, "fact": f.key if f else None})

    ser = FactSerializer(db)
    return {
        "unit_note": "Money values are shown in million UZS.",
        "months": month_rows,
        "periods": period_rows,
        "ratios": ratios,
        "cash_on_hand": cash,
        "has": {"bank_statement": any(d.doc_type == "bank_statement" for d in docs),
                "form2": bool(period_rows), "ratios": any(r["fact"] for r in ratios)},
        "facts": ser.by_key(chosen),
    }
