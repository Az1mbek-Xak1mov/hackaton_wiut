"""Description of a public upload that is not a recognised statutory form (≤ 3 sentences, verified).

The numbers the system could read are registered as facts of the document first, so the description can only
cite what is on the page, and each cited number opens its page in the evidence pane."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.extraction.models import Fact
from app.modules.extraction.service import fact_to_draft, persist_facts
from app.modules.llm import prompts
from app.modules.llm.narrative import redactor, run_verified_draft
from app.modules.llm.provider import available, status as llm_status

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2   # public path: keep inside the 55 s budget


def register_readable_numbers(db: Session, doc: Document) -> dict:
    from app.pipeline.readable import is_identifier, storable_value
    from app.pipeline.types import FactDraft

    existing = db.scalars(select(Fact).where(Fact.document_id == doc.id, Fact.method == "readable")).all()
    if existing:
        return {f.key: fact_to_draft(f) for f in existing}
    readable = (doc.summary or {}).get("readable") or {}
    drafts = []
    for i, n in enumerate(readable.get("numbers") or []):
        # summaries stored before the identifier filter may still hold account numbers (20 digits): those are
        # identifiers, and would not fit facts.value Numeric(20, 4) anyway
        if not storable_value(n.get("value")) or is_identifier(str(n.get("text") or "")):
            continue
        drafts.append(FactDraft(field=f"readable.number.{i + 1}", label=(n.get("label") or f"Number on page {n.get('page_n')}")[:255],
                                value=float(n["value"]), unit="count", kind="extracted", printed=str(n.get("text") or "")[:64],
                                page_n=n.get("page_n"), bbox=n.get("bbox"), passage=n.get("label") or "",
                                confidence=1.0, method="readable", note="read from the document; meaning not interpreted"))
    rows, _ = persist_facts(db, drafts, document=doc)
    return {r.key: fact_to_draft(r) for r in rows}


def describe_document(db: Session, doc: Document) -> dict:
    """Runner hook for public uploads. {text, mode: llm|none}; never blocks the truthful 'what I could read'."""
    if doc.doc_type in ("form1", "form2", "bank_statement", "loan_application"):
        return {"text": "", "mode": "none"}
    if not available(db):
        st = llm_status(db)
        return {"text": "", "mode": "none", "llm_status": st["code"], "llm_status_text": st["text"]}
    facts = register_readable_numbers(db, doc)
    readable = (doc.summary or {}).get("readable") or {}
    stirs = list(readable.get("stirs") or [])
    payload = {"task": "Describe this document in at most three sentences.",
               "type_guess": doc.doc_type, "type_reason": doc.type_reason, "language": doc.language,
               "pages": readable.get("pages"), "text_excerpt": (readable.get("text_excerpt") or "")[:1200]}
    run = run_verified_draft(db, purpose="unknown_doc", system_prompt=prompts.load("describe"), payload=payload,
                             facts=facts, finding_ids=set(), redact=redactor([], stirs), run_fields={},
                             generation=1, max_attempts=MAX_ATTEMPTS, document_id=doc.id)
    if run is None:
        st = llm_status(db)
        if st["code"] not in ("ok", "error"):   # the provider refused (no credits / bad key) mid-way
            return {"text": "", "mode": "none", "llm_status": st["code"], "llm_status_text": st["text"]}
        return {"text": "", "mode": "none", "note": "description not shown: no draft passed the citation verifier"}
    return {"text": run.output, "mode": "llm", "verified": True}
