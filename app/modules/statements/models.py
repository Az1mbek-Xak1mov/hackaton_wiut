from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class Transaction(BaseModel):
    __tablename__ = "transactions"
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    row_n: Mapped[int] = mapped_column(Integer, nullable=False)
    booked_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)   # UZS, + inflow
    counterparty: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    counterparty_stir: Mapped[str | None] = mapped_column(String(9), nullable=True)
    account: Mapped[str | None] = mapped_column(String(20), nullable=True)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other", index=True)
    category_source: Mapped[str] = mapped_column(String(8), nullable=False, default="rule")
    category_conf: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    recurring_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
