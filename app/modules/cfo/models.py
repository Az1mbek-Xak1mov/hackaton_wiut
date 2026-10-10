from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class CfoThread(BaseModel):
    __tablename__ = "cfo_threads"
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class CfoMessage(BaseModel):
    __tablename__ = "cfo_messages"
    thread_id: Mapped[int] = mapped_column(ForeignKey("cfo_threads.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)   # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    citations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tool_trace: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="llm")
