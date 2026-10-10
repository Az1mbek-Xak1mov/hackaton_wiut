from datetime import date, datetime
from typing import List

from sqlalchemy import (JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, SmallInteger, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import BaseModel


class Document(BaseModel):
    __tablename__ = "documents"
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mime: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")   # relative to FILES_DIR
    owner_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="bank")  # bank | owner | public
    borrower_id: Mapped[int | None] = mapped_column(ForeignKey("borrowers.id", ondelete="SET NULL"), nullable=True, index=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    type_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    type_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    stir: Mapped[str | None] = mapped_column(String(9), nullable=True)
    text_layer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    failure_cause: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    pages: Mapped[List["Page"]] = relationship(back_populates="document", cascade="all, delete-orphan",
                                               order_by="Page.n")


class Page(BaseModel):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "n", name="uq_page_document_n"),)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    n: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    width: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    height: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    image_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")    # relative to FILES_DIR
    image_scale: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    ocr_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ocr_mean_conf: Mapped[float | None] = mapped_column(Float, nullable=True)
    skew_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    blur_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    words: Mapped[list] = mapped_column(JSON, nullable=False, default=list)   # [text,x0,y0,x1,y1,conf]
    document: Mapped[Document] = relationship(back_populates="pages")
