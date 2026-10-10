from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import Stir


class BorrowerIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    stir: Stir
    industry: str = Field(default="", max_length=128)
    region: str = Field(default="", max_length=128)
    employees: int | None = Field(default=None, ge=0)
    since: int | None = Field(default=None, ge=1900, le=2100)


class ApplicationCreate(BaseModel):
    borrower: BorrowerIn
    number: str | None = Field(default=None, pattern=r"^APP-\d{4}-\d{4}$")
    requested_amount: float | None = Field(default=None, gt=0, description="kUZS")
    term_months: int | None = Field(default=None, ge=1, le=360)
    rate_pct: float | None = Field(default=None, ge=0, le=100)
    purpose: str = Field(default="", max_length=255)
    collateral: str = Field(default="", max_length=255)
    declared: dict = Field(default_factory=dict)
    received_on: date | None = None


class DecisionCreate(BaseModel):
    outcome: Literal["recommend", "decline", "request_info"]
    reasoning: str = Field(min_length=20, max_length=5000)
    evidence_reviewed: list[str] = Field(default_factory=list, max_length=500)


class FindingStateUpdate(BaseModel):
    state: Literal["open", "resolved", "dismissed"]
    note: str = Field(default="", max_length=2000)
