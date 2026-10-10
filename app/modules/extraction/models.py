from sqlalchemy import JSON, Float, ForeignKey, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class Fact(BaseModel):
    """The evidence store: every figure shown anywhere is a row here."""
    __tablename__ = "facts"
    key: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="extracted")   # extracted | computed | aggregate
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True)
    borrower_id: Mapped[int | None] = mapped_column(ForeignKey("borrowers.id", ondelete="CASCADE"), nullable=True, index=True)
    field: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    line_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    period_label: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    value: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="kUZS")
    printed: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    page_n: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    label_bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    passage: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    method: Mapped[str] = mapped_column(String(24), nullable=False, default="dictionary")
    formula: Mapped[str] = mapped_column(Text, nullable=False, default="")
    inputs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")   # auto | verified | corrected | flagged
