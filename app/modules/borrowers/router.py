from typing import Literal

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.exceptions import NotFoundError
from app.core.scopes import Scope
from app.modules.applications.models import Decision
from app.modules.audit import service as audit
from app.modules.auth.deps import require_scope
from app.modules.borrowers.models import Borrower, Loan
from app.modules.borrowers.schemas import BorrowerCreate, LoanCreate, ReviewOutcomeCreate
from app.modules.borrowers.service import BorrowerService
from app.modules.monitoring.service import borrower_detail, borrower_items

router = APIRouter(prefix="/api/v1", tags=["borrowers"])
read = require_scope(Scope.BORROWER_READ)
write = require_scope(Scope.BORROWER_WRITE)


@router.get("/borrowers")
def list_borrowers(status: Literal["stable", "watch", "attn", "unknown", "not_monitored"] | None = None,
                   db: Session = Depends(get_db),
                   _=Depends(read)):
    return borrower_items(db, status)


@router.get("/borrowers/{ref}")
def get_borrower(ref: str, db: Session = Depends(get_db), _=Depends(read)):
    """`ref` = loan id (L-2025-0417) or, for a business without a loan, the borrower uuid."""
    s = BorrowerService(db)
    try:
        b = db.scalars(select(Borrower).where(Borrower.uuid == UUID(ref))).first()
    except ValueError:
        b = None
    if b is not None:
        loan = db.scalars(select(Loan).where(Loan.borrower_id == b.id).order_by(Loan.disbursed_on.desc())).first()
        return borrower_detail(db, loan, b)
    return borrower_detail(db, s.loan_or_404(ref))


@router.post("/borrowers", status_code=201)
def create_borrower(data: BorrowerCreate, db: Session = Depends(get_db), actor=Depends(write)):
    b = BorrowerService(db).upsert_borrower(data.model_dump(), actor)
    return {"uuid": str(b.uuid), "name": b.name, "stir": b.stir}


@router.post("/loans", status_code=201)
def create_loan(data: LoanCreate, db: Session = Depends(get_db), actor=Depends(write)):
    s = BorrowerService(db)
    b = s.by_stir(data.borrower_stir)
    if b is None:
        raise NotFoundError("borrower")
    payload = data.model_dump(exclude={"borrower_stir"})
    loan = s.create_loan(b, payload, actor)
    return {"uuid": str(loan.uuid), "loan_id": loan.contract_no}


@router.post("/borrowers/{loan_id}/review-outcome", status_code=201)
def record_review_outcome(loan_id: str, data: ReviewOutcomeCreate, db: Session = Depends(get_db),
                          actor=Depends(require_scope(Scope.DECISION_WRITE))):
    """Officer's monitoring review outcome (H6), kept separate from the system status."""
    loan = BorrowerService(db).loan_or_404(loan_id)
    dec = Decision(borrower_id=loan.borrower_id, officer_id=actor.id, outcome=data.outcome,
                   reasoning=data.reasoning, evidence_reviewed=list(data.evidence_reviewed))
    db.add(dec)
    db.flush()
    audit.record(db, actor, "review_outcome", "loan", loan.uuid,
                 after={"outcome": data.outcome, "reasoning": data.reasoning})
    db.commit()
    return {"uuid": str(dec.uuid), "outcome": dec.outcome}
