"""Narrative for an application: LLM draft (when on) checked by the citation verifier, else the template.

Every attempt is stored in `narrative_runs` with its verifier report; only accepted text is shown as
"AI draft, verified numbers". The template is labelled as such.
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.extraction.models import Fact
from app.modules.extraction.service import fact_to_draft
from app.modules.llm.models import NarrativeRun
from app.modules.llm.provider import available, status as llm_status

logger = logging.getLogger(__name__)


def application_fact_drafts(db: Session, application, ctx) -> dict:
    facts = {f.key: f for f in getattr(ctx, "facts", []) or [] if getattr(f, "key", None)}
    for f in db.scalars(select(Fact).where(Fact.application_id == application.id)).all():
        facts[f.key] = fact_to_draft(f)
    return facts


def next_generation(db: Session, application_id: int | None = None, borrower_id: int | None = None) -> int:
    stmt = select(func.max(NarrativeRun.generation))
    stmt = stmt.where(NarrativeRun.application_id == application_id) if application_id else \
        stmt.where(NarrativeRun.borrower_id == borrower_id)
    return (db.scalar(stmt) or 0) + 1


def generate_application_narrative(db: Session, application, ctx, findings, ratio_drafts) -> NarrativeRun | None:
    facts = application_fact_drafts(db, application, ctx)
    generation = next_generation(db, application_id=application.id)

    if available(db):
        from app.modules.llm.narrative import generate as llm_generate
        try:
            accepted = llm_generate(db, application=application, ctx=ctx, findings=findings,
                                    ratio_facts=ratio_drafts, facts=facts, generation=generation)
            if accepted is not None:
                return accepted
        except Exception:
            logger.exception("LLM narrative failed for %s; falling back to the template", application.number)
    llm_attempts = db.scalar(select(func.count(NarrativeRun.id)).where(
        NarrativeRun.application_id == application.id, NarrativeRun.generation == generation)) or 0

    try:
        from app.pipeline.narrative import template_narrative
        from app.pipeline.verify import verify
    except ImportError:
        logger.warning("narrative template / verifier not available in this build")
        return None
    text = template_narrative(ctx, findings, ratio_drafts)
    report = verify(text, facts)
    report = report if isinstance(report, dict) else {"ok": bool(report)}
    st = llm_status(db)   # why no AI draft: switched off, no key, no credits, provider error, or verifier rejections
    report = {**report, "llm_status": st["code"], "llm_status_text": st["text"]}
    run = NarrativeRun(application_id=application.id, generation=generation, attempt=llm_attempts + 1, mode="template",
                       fact_set=_fact_set(facts), output=text, verifier_report=_safe(report),
                       accepted=bool(report.get("ok")))
    db.add(run)
    db.flush()
    return run


def _fact_set(facts: dict) -> list:
    out = []
    for k, f in facts.items():
        try:
            from app.pipeline.compute import fact_display
            display, unit = fact_display(f)
        except Exception:
            display, unit = str(f.value), f.unit
        out.append({"id": k, "label": f.label, "value": f.value, "unit": f.unit, "display": f"{display} {unit}".strip()})
    return out


def _safe(obj):
    from app.modules.jobs.runner import _jsonable
    return _jsonable(obj)
