from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.auth.deps import get_optional_user
from app.modules.documents.service import DocumentService
from app.modules.statements.models import Transaction

router = APIRouter(prefix="/api/v1", tags=["statements"])


@router.get("/documents/{doc_uuid}/transactions")
def transactions(doc_uuid: UUID, request: Request, category: str | None = None, limit: int = 500, offset: int = 0,
                 db: Session = Depends(get_db), user=Depends(get_optional_user)):
    s = DocumentService(db)
    doc = s.doc_or_404(doc_uuid)
    s.ensure_access(request, user, doc)
    stmt = select(Transaction).where(Transaction.document_id == doc.id)
    if category:
        stmt = stmt.where(Transaction.category == category)
    rows = db.scalars(stmt.order_by(Transaction.row_n).offset(max(0, offset)).limit(min(max(1, limit), 2000))).all()
    return {"items": [{"row_n": t.row_n, "booked_on": t.booked_on.isoformat(), "amount": float(t.amount),
                       "counterparty": t.counterparty, "counterparty_stir": t.counterparty_stir, "account": t.account,
                       "purpose": t.purpose, "category": t.category, "category_source": t.category_source,
                       "category_conf": t.category_conf, "recurring_group": t.recurring_group} for t in rows]}
