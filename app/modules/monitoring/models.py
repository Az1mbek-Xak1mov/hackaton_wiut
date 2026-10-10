from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class MonitoringRun(BaseModel):
    __tablename__ = "monitoring_runs"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")   # queued | running | done | failed
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    thresholds: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class MonitoringResult(BaseModel):
    __tablename__ = "monitoring_results"
    run_id: Mapped[int] = mapped_column(ForeignKey("monitoring_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    borrower_id: Mapped[int] = mapped_column(ForeignKey("borrowers.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    indicators: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    prev_status: Mapped[str | None] = mapped_column(String(8), nullable=True)
