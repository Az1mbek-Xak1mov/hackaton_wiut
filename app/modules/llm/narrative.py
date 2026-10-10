"""Grounded narrative (docs/plan/02-PIPELINE.md §7): fact set → LLM draft → citation verifier → up to 3 attempts
with the verifier report as feedback. Every attempt is stored in `narrative_runs`; None means "use the template"."""
import json
import logging
import re

from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.llm import prompts
from app.modules.llm.models import NarrativeRun
from app.modules.llm.provider import LLMError, LLMUnavailable, available, complete

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


def redactor(names: list[str], stirs: list[str]):
    """LLM_REDACT: the borrower's name and STIR never leave the bank, whatever field they hide in."""
    pats = []
    for n in names:
        if n and len(n) > 2:
            pats.append((re.compile(re.escape(n), re.IGNORECASE), "the borrower"))
    for s in stirs:
        if s and len(s) == 9:
            pats.append((re.compile(rf"{s[:3]}\s?{s[3:6]}\s?{s[6:]}"), "[STIR]"))

    def apply(text: str) -> str:
        if not settings.LLM_REDACT:
            return text
        for rx, repl in pats:
            text = rx.sub(repl, text)
        return text
    return apply


def finding_payload(findings: list) -> tuple[list[dict], set[str]]:
    out, ids, counter = [], set(), {}
    for f in findings:
        counter[f.rule_id] = counter.get(f.rule_id, 0) + 1
        fid = f"{f.rule_id}-{counter[f.rule_id]}"
        ids.update({fid, f.rule_id})
        out.append({"id": fid, "severity": f.severity, "label": f.label, "title": f.title,
                    "evidence": list(f.evidence or [])})
    return out, ids


def run_verified_draft(db: Session, *, purpose: str, system_prompt: str, payload: dict, facts: dict,
                       finding_ids: set[str], redact, run_fields: dict, generation: int,
                       max_attempts: int = MAX_ATTEMPTS, application_id: int | None = None,
                       document_id: int | None = None) -> NarrativeRun | None:
    """Shared loop for narratives and descriptions. Returns the accepted run, or None after `max_attempts`
    rejected drafts (or when the provider fails); every attempt is stored."""
    from app.pipeline.verify import facts_for_prompt, feedback_message, verify

    fact_set = facts_for_prompt(facts)
    user = redact(json.dumps({**payload, "facts": fact_set}, ensure_ascii=False))
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user}]
    for attempt in range(1, max_attempts + 1):
        try:
            res = complete(db, purpose, messages, application_id=application_id, document_id=document_id)
        except (LLMUnavailable, LLMError) as exc:
            logger.warning("%s: LLM call failed on attempt %s: %s", purpose, attempt, exc)
            return None
        text = (res.text or "").strip()
        report = verify(text, facts, finding_ids)
        run = NarrativeRun(generation=generation, attempt=attempt, mode="llm", fact_set=fact_set, output=text,
                           verifier_report=_jsonable(report), accepted=bool(report.get("ok")) and bool(text),
                           llm_call_id=res.call_id, **run_fields)
        db.add(run)
        db.flush()
        if run.accepted:
            return run
        messages += [res.message or {"role": "assistant", "content": text},
                     {"role": "user", "content": feedback_message(report)}]
    return None


def generate(db: Session, *, application, ctx, findings, ratio_facts, facts, generation) -> NarrativeRun | None:
    """Hook called by app.modules.applications.narrative. None → the caller writes the template."""
    if not available(db):
        return None
    from app.pipeline.narrative import narrative_fact_set

    fset = narrative_fact_set(ctx, findings, ratio_facts)
    payload_findings, finding_ids = finding_payload(findings)
    app_info = getattr(ctx, "application", {}) or {}
    redact = redactor([app_info.get("borrower_name", "")], [app_info.get("borrower_stir") or ""])
    return run_verified_draft(
        db, purpose="narrative", system_prompt=prompts.load("narrative"),
        payload={"task": "Write the AI analysis for this loan application.", "findings": payload_findings},
        facts=fset, finding_ids=finding_ids, redact=redact, run_fields={"application_id": application.id},
        generation=generation, application_id=application.id)


def _jsonable(obj):
    from app.modules.jobs.runner import _jsonable as j
    return j(obj)
