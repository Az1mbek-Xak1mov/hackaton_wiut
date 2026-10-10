from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class FactReview(BaseModel):
    __tablename__ = "fact_reviews"
    fact_id: Mapped[int] = mapped_column(ForeignKey("facts.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(8), nullable=False)   # verify | correct | flag
    old_value: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    new_value: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
