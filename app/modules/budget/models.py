from sqlalchemy import JSON, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class BudgetLine(BaseModel):
    """The owner's monthly plan. category 'total' is the whole business; other categories (statement
    categories such as salary, supplier_payment) are optional spending limits."""
    __tablename__ = "budget_lines"
    __table_args__ = (UniqueConstraint("borrower_id", "month", "category", name="uq_budget_line"),)
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id", ondelete="CASCADE"), index=True, nullable=False)
    month: Mapped[str] = mapped_column(String(7), nullable=False)          # YYYY-MM
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="total")
    planned_income: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)    # UZS
    planned_spending: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)  # UZS


class BudgetAdvice(BaseModel):
    """One run of the advice rules (+ optional plain-language explanation), kept so GET shows the last one."""
    __tablename__ = "budget_advice"
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id", ondelete="CASCADE"), index=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="rules")   # llm | rules
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
