"""AI explanation on the borrower page: LLM draft verified like the loan narrative, else a template built only
from the monitoring findings and the facts they cite (each sentence kept only if the verifier accepts it)."""
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.borrowers.models import Borrower
from app.modules.extraction.models import Fact
from app.modules.extraction.service import fact_to_draft
from app.modules.llm import prompts
from app.modules.llm.models import NarrativeRun
from app.modules.llm.narrative import finding_payload, redactor, run_verified_draft
from app.modules.llm.provider import available, status as llm_status
from app.modules.monitoring.models import MonitoringResult, MonitoringRun
from app.modules.reconcile.models import Finding

logger = logging.getLogger(__name__)

STATUS_WORDS = {"attn": "Attention", "watch": "Watch", "stable": "Stable"}
RULE = {"stable": "no indicator moved beyond its threshold",
        "watch": "one indicator moved, or the latest statement is late",
        "attn": "two or more indicators moved, or an installment was paid late"}
ASK = {"M01": "Ask what changed in sales this period and whether it is seasonal.",
       "M02": "Ask which customers have not paid and when payment is expected.",
       "M03": "Ask about unpaid suppliers and agreed payment terms.",
       "M04": "Ask how the next installment will be covered.",
       "M05": "Ask why the installment was paid late and whether it will recur.",
       "M06": "Request the missing statement."}


def _facts_for(db: Session, borrower: Borrower, findings: list[Finding]) -> dict:
    keys = {k for f in findings for k in (f.evidence or [])}
    rows = db.scalars(select(Fact).where(Fact.key.in_(list(keys) or ["-"]))).all()
    return {r.key: fact_to_draft(r) for r in rows}


def template_text(borrower_status: str, findings: list[Finding], facts: dict) -> str:
    from app.pipeline.verify import verify

    word = STATUS_WORDS.get(borrower_status, borrower_status)
    sentences = [f"The borrower is under {word} because {RULE.get(borrower_status, 'of the disclosed rules')}."]
    for f in findings:
        cites = [k for k in (f.evidence or []) if k in facts]
        s = f"{f.title.rstrip('.')}" + (f" [{', '.join(cites)}]." if cites else ".")
        if verify(s, facts, check_forbidden=False).get("ok"):
            sentences.append(s)
    asks = [ASK[f.rule_id] for f in findings if f.rule_id in ASK]
    if asks:
        sentences.append("Before the review: " + " ".join(dict.fromkeys(asks)))
    sentences.append("Thresholds are illustrative; calibration against bank history is planned for the first pilot month.")
    return " ".join(sentences)


def generate_borrower_narrative(db: Session, borrower_id: int, run_id: int) -> NarrativeRun | None:
    borrower = db.get(Borrower, borrower_id)
    res = db.scalars(select(MonitoringResult).where(MonitoringResult.run_id == run_id,
                                                    MonitoringResult.borrower_id == borrower_id)).first()
    if borrower is None or res is None:
        return None
    findings = list(db.scalars(select(Finding).where(Finding.borrower_id == borrower_id,
                                                     Finding.monitoring_run_id == run_id).order_by(Finding.id)).all())
    facts = _facts_for(db, borrower, findings)
    generation = (db.scalar(select(func.max(NarrativeRun.generation)).where(NarrativeRun.borrower_id == borrower_id))
                  or 0) + 1
    if available(db) and findings:
        payload_findings, finding_ids = finding_payload(findings)
        run = run_verified_draft(
            db, purpose="narrative", system_prompt=prompts.load("borrower"),
            payload={"task": "Explain this borrower's monitoring status.",
                     "status": {"value": STATUS_WORDS.get(res.status, res.status), "rule": RULE.get(res.status, "")},
                     "findings": payload_findings},
            facts=facts, finding_ids=finding_ids, redact=redactor([borrower.name], [borrower.stir]),
            run_fields={"borrower_id": borrower_id}, generation=generation)
        if run is not None:
            return run
    from app.pipeline.verify import verify
    text = template_text(res.status, findings, facts)
    report = verify(text, facts, check_forbidden=False)
    st = llm_status(db)
    report = {**(report if isinstance(report, dict) else {"ok": bool(report)}),
              "llm_status": st["code"], "llm_status_text": st["text"]}
    attempts = db.scalar(select(func.count(NarrativeRun.id)).where(NarrativeRun.borrower_id == borrower_id,
                                                                   NarrativeRun.generation == generation)) or 0
    run = NarrativeRun(borrower_id=borrower_id, generation=generation, attempt=attempts + 1, mode="template",
                       fact_set=[{"id": k, "label": f.label} for k, f in facts.items()], output=text,
                       verifier_report=report, accepted=bool(report.get("ok")))
    db.add(run)
    db.flush()
    return run


def borrowers_to_explain(db: Session, run: MonitoringRun) -> list[int]:
    return list(db.scalars(select(MonitoringResult.borrower_id).where(MonitoringResult.run_id == run.id,
                                                                      MonitoringResult.status.in_(("watch", "attn"))))
                .all())
