from sqlalchemy import JSON, Boolean, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class LlmCall(BaseModel):
    __tablename__ = "llm_calls"
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)   # narrative | cfo | unmapped_line | unknown_doc
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")


class NarrativeRun(BaseModel):
    __tablename__ = "narrative_runs"
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True)
    borrower_id: Mapped[int | None] = mapped_column(ForeignKey("borrowers.id", ondelete="CASCADE"), nullable=True, index=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)   # one generation = up to 3 attempts
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)   # llm | template
    fact_set: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verifier_report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    llm_call_id: Mapped[int | None] = mapped_column(ForeignKey("llm_calls.id", ondelete="SET NULL"), nullable=True)
