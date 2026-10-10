"""Facts: persistence of pipeline drafts and the one serializer every endpoint uses."""
import math
import secrets
import string
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.formatting import display_for
from app.modules.documents.models import Document, Page
from app.modules.documents.periods import resolve_label
from app.modules.extraction.models import Fact

_ALPHABET = string.digits + string.ascii_lowercase


def fact_display(f: Fact) -> tuple[str, str]:
    """Same strings the narrative/LLM sees: the pipeline's formatter when present, ours otherwise."""
    try:
        from app.pipeline.compute import format_display
    except Exception:  # pipeline not deployed in this build
        return display_for(f.value, f.unit)
    signed = f.unit == "pct" and ".change" in (f.field or "")
    return format_display(float(f.value), f.unit, signed=signed)


def new_key() -> str:
    return "f_" + "".join(secrets.choice(_ALPHABET) for _ in range(6))


def _clip(s: str | None, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def unique_keys(db: Session, wanted: list[str | None]) -> tuple[list[str], dict[str, str]]:
    """Returns final keys (one per draft) and a remap {draft_key: final_key} for drafts whose key was taken."""
    proposed = [k if k else new_key() for k in wanted]
    taken = set(db.scalars(select(Fact.key).where(Fact.key.in_(proposed))).all())
    seen: set[str] = set()
    final, remap = [], {}
    for orig, key in zip(wanted, proposed):
        while key in taken or key in seen:
            key = new_key()
        seen.add(key)
        final.append(key)
        if orig and orig != key:
            remap[orig] = key
    return final, remap


def persist_facts(db: Session, drafts: Iterable, *, document: Document | None = None, application_id: int | None = None,
                  borrower_id: int | None = None, attach_computed: bool = False) -> tuple[list[Fact], dict[str, str]]:
    """FactDraft → Fact rows (flush, no commit). Keys are assigned here unless the draft brings a free one.
    `attach_computed` keeps derived facts on the document (single-document public analysis)."""
    drafts = [d for d in drafts if d is not None and d.value is not None and math.isfinite(float(d.value))]
    keys, remap = unique_keys(db, [getattr(d, "key", None) for d in drafts])
    rows = []
    for d, key in zip(drafts, keys):
        d.key = key
        period = d.period_label
        if document is not None:
            period = resolve_label(period, document.doc_type, document.period_start, document.period_end)
        row = Fact(
            key=key, kind=d.kind or "extracted",
            document_id=document.id if document is not None and (d.kind != "computed" or attach_computed) else None,
            application_id=application_id, borrower_id=borrower_id if borrower_id else (document.borrower_id if document else None),
            field=_clip(d.field, 128), label=_clip(d.label, 255), line_code=_clip(d.line_code, 8) or None,
            period_label=_clip(period, 16), value=float(d.value), unit=_clip(d.unit or "kUZS", 16),
            printed=_clip(d.printed, 64), page_n=d.page_n, bbox=list(d.bbox) if d.bbox else None,
            label_bbox=list(d.label_bbox) if d.label_bbox else None, passage=d.passage or "",
            confidence=float(d.confidence if d.confidence is not None else 1.0), method=_clip(d.method, 24),
            formula=d.formula or "", inputs=[remap.get(i, i) for i in (d.inputs or [])], note=d.note or "",
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows, remap


def fact_to_draft(f: Fact):
    from app.pipeline.types import FactDraft

    return FactDraft(field=f.field, label=f.label, value=float(f.value), unit=f.unit, kind=f.kind,
                     line_code=f.line_code, period_label=f.period_label, printed=f.printed, page_n=f.page_n,
                     bbox=f.bbox, label_bbox=f.label_bbox, passage=f.passage, confidence=f.confidence,
                     method=f.method, formula=f.formula, inputs=list(f.inputs or []), note=f.note, key=f.key)


class FactSerializer:
    """Fact rows → the `Fact` shape of docs/plan/09-API.md (with display strings and page geometry)."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._docs: dict[int, Document] = {}
        self._pages: dict[tuple[int, int], object] = {}

    def _preload(self, facts: list[Fact]) -> None:
        doc_ids = {f.document_id for f in facts if f.document_id and f.document_id not in self._docs}
        if not doc_ids:
            return
        for d in self.db.scalars(select(Document).where(Document.id.in_(doc_ids))).all():
            self._docs[d.id] = d
        # page geometry only (the `words` JSON is large and not needed here)
        for p in self.db.execute(select(Page.document_id, Page.n, Page.width, Page.height, Page.image_path)
                                 .where(Page.document_id.in_(doc_ids))).all():
            self._pages[(p.document_id, p.n)] = p

    def one(self, f: Fact) -> dict:
        self._preload([f])
        return self._dump(f)

    def many(self, facts: Iterable[Fact]) -> list[dict]:
        facts = list(facts)
        self._preload(facts)
        return [self._dump(f) for f in facts]

    def by_key(self, facts: Iterable[Fact]) -> dict[str, dict]:
        return {d["key"]: d for d in self.many(facts)}

    def _dump(self, f: Fact) -> dict:
        display, display_unit = fact_display(f)
        doc = self._docs.get(f.document_id) if f.document_id else None
        page = self._pages.get((f.document_id, f.page_n)) if doc and f.page_n else None
        return {
            "key": f.key, "uuid": str(f.uuid), "field": f.field, "label": f.label,
            "value": float(f.value), "unit": f.unit, "display": display, "display_unit": display_unit,
            "printed": f.printed, "period_label": f.period_label, "line_code": f.line_code, "kind": f.kind,
            "page_n": f.page_n, "bbox": f.bbox, "label_bbox": f.label_bbox,
            "page_width": page.width if page else None, "page_height": page.height if page else None,
            "page_image_url": (f"/api/v1/documents/{doc.uuid}/pages/{f.page_n}.png"
                               if page is not None and page.image_path else None),
            "passage": f.passage, "confidence": f.confidence, "method": f.method, "formula": f.formula,
            "inputs": list(f.inputs or []), "note": f.note, "status": f.status,
            "document": ({"uuid": str(doc.uuid), "filename": doc.filename, "doc_type": doc.doc_type} if doc else None),
        }


def facts_by_keys(db: Session, keys: list[str]) -> list[Fact]:
    if not keys:
        return []
    return list(db.scalars(select(Fact).where(Fact.key.in_(keys))).all())
