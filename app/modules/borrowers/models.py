from datetime import date

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class Borrower(BaseModel):
    __tablename__ = "borrowers"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stir: Mapped[str | None] = mapped_column(String(9), unique=True, nullable=True)   # optional at sign-up
    industry: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    region: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    employees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    since: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)   # year founded
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Loan(BaseModel):
    __tablename__ = "loans"
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id", ondelete="CASCADE"), index=True, nullable=False)
    contract_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)   # shown as loan_id, e.g. L-2025-0417
    loan_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    purpose: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    original_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)     # kUZS
    outstanding: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)          # kUZS
    installment: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)          # kUZS
    rate_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    due_day: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=15)
    term_months: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    paid_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    disbursed_on: Mapped[date] = mapped_column(Date, nullable=False)
    maturity_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    collateral: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class Repayment(BaseModel):
    __tablename__ = "repayments"
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id", ondelete="CASCADE"), index=True, nullable=False)
    n: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    source_txn_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True)
