from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class Application(BaseModel):
    __tablename__ = "applications"
    number: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id", ondelete="CASCADE"), index=True, nullable=False)
    requested_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)   # kUZS
    term_months: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    rate_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    repayment: Mapped[str] = mapped_column(String(16), nullable=False, default="annuity")
    purpose: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    collateral: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    declared: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)   # manual entries (e.g. declared debts)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    analysed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApplicationDocument(BaseModel):
    __tablename__ = "application_documents"
    __table_args__ = (UniqueConstraint("application_id", "document_id", name="uq_application_document"),)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    required_type: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Decision(BaseModel):
    """Written only by a human (H5). The system never fills `outcome`."""
    __tablename__ = "decisions"
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True)
    borrower_id: Mapped[int | None] = mapped_column(ForeignKey("borrowers.id", ondelete="CASCADE"), nullable=True, index=True)
    officer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reviewed: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
