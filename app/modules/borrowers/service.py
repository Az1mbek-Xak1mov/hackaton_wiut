from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.scopes import PORTFOLIO_ROLES
from app.modules.audit import service as audit
from app.modules.borrowers.models import Borrower, Loan, Repayment

BORROWER_FIELDS = ("name", "stir", "industry", "region", "employees", "since", "owner_user_id")
LOAN_FIELDS = ("contract_no", "original_amount", "outstanding", "installment", "term_months", "due_day")


class BorrowerService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def by_stir(self, stir: str) -> Borrower | None:
        return self.db.scalars(select(Borrower).where(Borrower.stir == stir)).first()

    def upsert_borrower(self, data: dict, actor, commit: bool = True) -> Borrower:
        """Borrowers are keyed by STIR; a second application from the same business reuses the row."""
        b = self.by_stir(data["stir"])
        if b is None:
            b = Borrower(**{k: data.get(k) for k in ("name", "stir", "industry", "region", "employees", "since",
                                                     "owner_user_id") if data.get(k) is not None})
            b.industry = b.industry or ""
            b.region = b.region or ""
            self.db.add(b)
            self.db.flush()
            audit.record(self.db, actor, "create", "borrower", b.uuid, after=audit.snapshot(b, BORROWER_FIELDS))
        else:
            before = audit.snapshot(b, BORROWER_FIELDS)
            for k in ("name", "industry", "region", "employees", "since", "owner_user_id"):
                if data.get(k) is not None:
                    setattr(b, k, data[k])
            self.db.flush()
            after = audit.snapshot(b, BORROWER_FIELDS)
            if after != before:
                audit.record(self.db, actor, "update", "borrower", b.uuid, before=before, after=after)
        if commit:
            self.db.commit()
            self.db.refresh(b)
        return b

    def create_loan(self, borrower: Borrower, data: dict, actor, commit: bool = True) -> Loan:
        loan = self.db.scalars(select(Loan).where(Loan.contract_no == data["contract_no"])).first()
        if loan is None:
            loan = Loan(borrower_id=borrower.id, **{k: v for k, v in data.items() if k != "repayments"})
            self.db.add(loan)
            self.db.flush()
            audit.record(self.db, actor, "create", "loan", loan.uuid, after=audit.snapshot(loan, LOAN_FIELDS))
            for r in data.get("repayments") or []:
                self.db.add(Repayment(loan_id=loan.id, **r))
            self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(loan)
        return loan

    def loan_or_404(self, loan_id: str) -> Loan:
        loan = self.db.scalars(select(Loan).where(Loan.contract_no == loan_id)).first()
        if loan is None:
            raise NotFoundError("loan")
        return loan

    def visible_borrower_ids(self, user) -> set[int] | None:
        """None = all borrowers (bank roles); otherwise only the owner's own business."""
        if user.role in PORTFOLIO_ROLES:
            return None
        return set(self.db.scalars(select(Borrower.id).where(Borrower.owner_user_id == user.id)).all())

    def owner_borrower(self, user) -> Borrower:
        if user.role in PORTFOLIO_ROLES:
            # demo viewer / officer opening the owner surface: the business bound to the demo owner account
            b = self.db.scalars(select(Borrower).where(Borrower.owner_user_id.is_not(None)).order_by(Borrower.id)).first()
        else:
            b = self.db.scalars(select(Borrower).where(Borrower.owner_user_id == user.id).order_by(Borrower.id)).first()
        if b is None:
            raise NotFoundError("business", "No business is linked to this account")
        return b
