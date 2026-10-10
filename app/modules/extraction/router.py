from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.exceptions import AppException
from app.core.scopes import PORTFOLIO_ROLES, Scope
from app.modules.auth.deps import get_optional_user, has_scope
from app.modules.borrowers.models import Borrower
from app.modules.documents.models import Document
from app.modules.extraction.models import Fact
from app.modules.extraction.service import FactSerializer

router = APIRouter(prefix="/api/v1", tags=["facts"])


@router.get("/facts")
def facts_by_keys(request: Request, keys: str = Query(..., max_length=20000), db: Session = Depends(get_db),
                  user=Depends(get_optional_user)):
    """Evidence-store batch fetch. Anonymous callers only get facts of public (/analyse) documents."""
    wanted = [k.strip() for k in keys.split(",") if k.strip()][:500]
    if not wanted:
        raise AppException(code="keys_required", status_code=422, detail="Pass ?keys=f_a,f_b")
    facts = list(db.scalars(select(Fact).where(Fact.key.in_(wanted))).all())
    doc_ids = {f.document_id for f in facts if f.document_id}
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_(doc_ids))).all()} if doc_ids else {}

    def allowed(f: Fact) -> bool:
        d = docs.get(f.document_id) if f.document_id else None
        if d is not None and d.owner_kind == "public":
            return True
        if user is None or not has_scope(request, user, Scope.DOCUMENT_READ):
            return False
        if user.role in PORTFOLIO_ROLES:
            return True
        bid = f.borrower_id or (d.borrower_id if d else None)
        if bid is None:
            return False
        b = db.get(Borrower, bid)
        return b is not None and b.owner_user_id == user.id

    return {"facts": FactSerializer(db).many([f for f in facts if allowed(f)])}
