"""Wipe all domain data, keep the user accounts: `python -m app.reset_data --yes`.

Deletes documents (and their files under FILES_DIR), facts, findings, applications, borrowers, loans, monitoring,
narratives, LLM call logs, CFO threads, jobs, reviews and the audit log; then re-runs the start-up seed, which
recreates the owner account's business row. Refuses to run without --yes.
"""
import argparse
import logging
import shutil

from sqlalchemy import delete

from app.core.db import get_db_context
from app.modules.documents.storage import files_root

logger = logging.getLogger("app.reset_data")


def domain_tables():
    """Children before parents, so the deletes also work where the database does not cascade."""
    from app.modules.applications.models import Application, ApplicationDocument, Decision
    from app.modules.audit.models import AuditLog
    from app.modules.borrowers.models import Borrower, Loan, Repayment
    from app.modules.cfo.models import CfoMessage, CfoThread
    from app.modules.documents.models import Document, Page
    from app.modules.extraction.models import Fact
    from app.modules.jobs.models import Job
    from app.modules.llm.models import LlmCall, NarrativeRun
    from app.modules.monitoring.models import MonitoringResult, MonitoringRun
    from app.modules.reconcile.models import Finding
    from app.modules.reviews.models import FactReview
    from app.modules.statements.models import Transaction
    return [FactReview, CfoMessage, CfoThread, NarrativeRun, LlmCall, Decision, Finding, MonitoringResult,
            MonitoringRun, Repayment, Fact, Transaction, Page, ApplicationDocument, Application, Document, Loan,
            Borrower, Job, AuditLog]


def reset() -> dict:
    counts = {}
    with get_db_context() as db:
        for model in domain_tables():
            counts[model.__tablename__] = db.execute(delete(model)).rowcount
        db.commit()
    root = files_root()
    removed = 0
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
        removed += 1
    counts["files"] = removed
    from app.core.seed import seed
    seed()
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="app.reset_data", description=__doc__)
    ap.add_argument("--yes", action="store_true", help="really delete all domain data")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not a.yes:
        raise SystemExit("Refusing to delete data without --yes")
    for table, n in reset().items():
        logger.info("%s: %s removed", table, n)


if __name__ == "__main__":
    main()
