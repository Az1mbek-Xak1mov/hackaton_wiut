from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.formatting import fmt_number
from app.modules.statements.models import Transaction


def preview(db: Session, document_id: int, recurring: list | None) -> dict:
    """Category totals for the /analyse result; amounts are UZS → mln UZS display."""
    rows = db.scalars(select(Transaction).where(Transaction.document_id == document_id)).all()
    by_cat: dict[str, list[float]] = defaultdict(lambda: [0, 0.0, 0.0])
    for t in rows:
        c = by_cat[t.category]
        c[0] += 1
        amt = float(t.amount)
        if amt >= 0:
            c[1] += amt
        else:
            c[2] += -amt
    cats = [{"category": k, "count": v[0], "inflow_display": fmt_number(v[1] / 1e6, 1),
             "outflow_display": fmt_number(v[2] / 1e6, 1)} for k, v in by_cat.items()]
    cats.sort(key=lambda c: -c["count"])
    return {"count": len(rows), "unit": "mln UZS", "by_category": cats, "recurring": recurring or []}
