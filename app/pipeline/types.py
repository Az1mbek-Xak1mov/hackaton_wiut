"""Shared contract between the pipeline (pure functions, no DB) and the job runner.

The runner persists these drafts into the tables described in docs/plan/01-ARCHITECTURE.md.
Do not change field names without updating app/modules/jobs/runner.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float = 1.0  # 1.0 for a text layer, Tesseract conf/100 for OCR


@dataclass
class Row:
    page_n: int
    y: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class ParsedPage:
    n: int                      # 1-based
    width: float                # in the coordinate space of `words`
    height: float
    words: list[Word]
    image_path: str = ""        # 150-dpi PNG written by the parser
    image_scale: float = 1.0    # multiply word coords by this to get PNG pixel coords
    ocr_used: bool = False
    ocr_mean_conf: float | None = None
    skew_deg: float | None = None
    blur_score: float | None = None


@dataclass
class XlsxSheet:
    name: str
    rows: list[list[Any]]       # values (data_only), row index 0 == excel row 1


@dataclass
class ParsedDoc:
    kind: str                   # pdf_text | pdf_scan | image | xlsx | unsupported
    doc_type: str = "unknown"   # form1 | form2 | bank_statement | loan_application | tax_declaration | invoice | sales_ledger | unknown
    type_confidence: float = 0.0
    type_reason: str = ""       # human sentence, shown in the UI
    language: str = ""          # uz_latn | uz_cyrl | ru | en | mixed
    pages: list[ParsedPage] = field(default_factory=list)
    sheets: list[XlsxSheet] = field(default_factory=list)
    text_layer: bool = False
    failure_cause: str = ""     # non-empty => document status "failed" (but still return what was read)
    partial: bool = False       # stopped at the deadline / page cap
    period_start: date | None = None
    period_end: date | None = None
    stir: str | None = None


@dataclass
class FactDraft:
    field: str                  # canonical, e.g. "form2.010.net_revenue", "statement.inflow.sales_receipt.2026-03"
    label: str                  # human label, e.g. "Net revenue"
    value: float
    unit: str = "kUZS"          # kUZS | UZS | ratio | pct | days | count
    kind: str = "extracted"     # extracted | computed | aggregate
    line_code: str | None = None
    period_label: str = ""      # FY2025 | H1-2026 | Q3-2026 | 2026-09 | cur | prev
    printed: str = ""           # raw text as printed
    page_n: int | None = None
    bbox: list[float] | None = None        # value cell, in page word coords
    label_bbox: list[float] | None = None
    passage: str = ""
    confidence: float = 1.0
    method: str = "dictionary"  # dictionary | fuzzy | llm_fallback | ocr+dictionary | rule | compute | aggregate
    formula: str = ""
    inputs: list[str] = field(default_factory=list)   # fact keys (computed) or local refs
    note: str = ""
    key: str | None = None      # assigned by the runner if None (f_xxxxxx)


@dataclass
class TxnDraft:
    row_n: int
    booked_on: date
    amount: float               # UZS, + inflow / - outflow
    counterparty: str = ""
    counterparty_stir: str | None = None
    account: str | None = None
    purpose: str = ""
    category: str = "other"
    category_source: str = "rule"   # rule | model | user
    category_conf: float = 1.0
    recurring_group: str | None = None


@dataclass
class FindingDraft:
    rule_id: str                # R01..R12, M01..M06
    severity: str               # attn | watch | neutral | info
    label: str                  # "Undeclared obligation"
    title: str
    detail: str
    evidence: list[str] = field(default_factory=list)  # fact keys
    params: dict[str, Any] = field(default_factory=dict)
