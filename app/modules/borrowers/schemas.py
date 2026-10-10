from datetime import date

from pydantic import BaseModel, Field

from app.core.schemas import Stir


class BorrowerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    stir: Stir
    industry: str = Field(default="", max_length=128)
    region: str = Field(default="", max_length=128)
    employees: int | None = Field(default=None, ge=0)
    since: int | None = Field(default=None, ge=1900, le=2100)


class RepaymentIn(BaseModel):
    n: int = Field(ge=1)
    due_on: date
    paid_on: date | None = None
    amount: float | None = None


class LoanCreate(BaseModel):
    borrower_stir: Stir
    contract_no: str = Field(min_length=1, max_length=32)
    loan_type: str = Field(default="", max_length=32)
    purpose: str = Field(default="", max_length=255)
    original_amount: float = Field(gt=0, description="kUZS")
    outstanding: float = Field(ge=0, description="kUZS")
    installment: float = Field(gt=0, description="kUZS")
    rate_pct: float | None = Field(default=None, ge=0, le=100)
    due_day: int = Field(default=15, ge=1, le=28)
    term_months: int = Field(ge=1, le=360)
    paid_count: int = Field(default=0, ge=0)
    disbursed_on: date
    maturity_on: date | None = None
    collateral: dict = Field(default_factory=dict)
    repayments: list[RepaymentIn] = Field(default_factory=list)


class ReviewOutcomeCreate(BaseModel):
    outcome: str = Field(min_length=2, max_length=24)
    reasoning: str = Field(min_length=20, max_length=5000)
    evidence_reviewed: list[str] = Field(default_factory=list, max_length=500)
