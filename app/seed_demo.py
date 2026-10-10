"""Demo seed through the real pipeline: `python -m app.seed_demo` (compose: `--profile seed run seed`).

Creates the declared synthetic inputs (users, borrowers, the loan book with repayments, the bank's application
register) and then UPLOADS the documents through the same services the UI uses; the worker extracts,
reconciles, computes ratios, writes narratives and runs monitoring. No result is inserted here.

Idempotent and resumable: borrowers by STIR, loans by contract, applications by number, documents by
(borrower, sha256). Order = processing order (the queue is FIFO): Zilola's earlier quarter → an as-of
monitoring run for Zilola only → the three heroes → other applications → portfolio by loan_id → a full
monitoring run once every document is analysed.
"""
import argparse
import csv
import json
import logging
import time
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

from app.core.db import get_db_context
from app.core.security import hash_password
from app.core.timeutil import utcnow
from app.modules.applications.models import Application, ApplicationDocument
from app.modules.applications.service import ApplicationService, enqueue_analysis
from app.modules.auth.service import ensure_demo_user
from app.modules.borrowers.models import Borrower
from app.modules.borrowers.service import BorrowerService
from app.modules.documents.models import Document
from app.modules.documents.service import DocumentService
from app.modules.documents.storage import sha256
from app.modules.jobs.models import Job
from app.modules.monitoring.models import MonitoringRun
from app.modules.monitoring.service import start_run
from app.modules.users.models import User

logger = logging.getLogger("app.seed_demo")

DOC_SUFFIXES = {".pdf", ".xlsx", ".jpg", ".jpeg", ".png"}
EARLIER_QUARTER_AS_OF = date(2026, 7, 10)   # Q2 statements are due by the 10th of the following month
WAIT_LIMIT_S = 60 * 60


def seed_dir() -> Path:
    for p in (Path("/srv/data/seed"), Path(__file__).resolve().parents[1] / "data" / "seed"):
        if p.is_dir():
            return p
    raise SystemExit("data/seed not found (expected /srv/data/seed in the image or ./data/seed in the repo)")


def _files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in DOC_SUFFIXES)


def _truth(folder: Path) -> dict:
    t = folder / "truth.json"
    return json.loads(t.read_text(encoding="utf-8")) if t.is_file() else {}


def _mln_to_k(v) -> float:
    return round(float(v) * 1000.0, 2)


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, 28)


# ------------------------------------------------------------------------------------------- declared inputs

def seed_users() -> dict[str, int]:
    with get_db_context() as db:
        officer = ensure_demo_user(db, "officer")
        officer.full_name = "G. Abdullayeva"
        owner = ensure_demo_user(db, "owner")
        viewer = db.scalars(select(User).where(User.email == "demo@converza.uz")).first()
        if viewer is None:
            import secrets
            viewer = User(email="demo@converza.uz", full_name="Demo viewer", role="demo_viewer",
                          password_hash=hash_password(secrets.token_hex(24)), is_active=True)
            db.add(viewer)
        db.commit()
        return {"officer": officer.id, "owner": owner.id, "viewer": viewer.id}


def seed_loan_book(root: Path) -> dict[str, int]:
    """loan_book.csv (declared synthetic loan book, amounts in mln UZS) → borrowers, loans, repayments.
    Returns {loan_id: borrower_id}."""
    out: dict[str, int] = {}
    with open(root / "loan_book.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    with get_db_context() as db:
        s = BorrowerService(db)
        for r in rows:
            b = s.upsert_borrower({"name": r["name"], "stir": r["stir"], "industry": r["industry"],
                                   "region": r["region"]}, None, commit=False)
            disbursed = date.fromisoformat(r["disbursed_on"])
            term = int(r["term_months"])
            reps = []
            for p in json.loads(r["repayments"] or "[]"):
                reps.append({"n": int(p["n"]), "due_on": date.fromisoformat(p["due"]),
                             "paid_on": date.fromisoformat(p["paid"]) if p.get("paid") else None,
                             "amount": _mln_to_k(r["installment"])})
            s.create_loan(b, {"contract_no": r["loan_id"], "original_amount": _mln_to_k(r["original"]),
                              "outstanding": _mln_to_k(r["outstanding"]), "installment": _mln_to_k(r["installment"]),
                              "rate_pct": float(r["rate_pct"]) if r.get("rate_pct") else None,
                              "due_day": int(r["due_day"]), "term_months": term, "paid_count": int(r["paid_count"]),
                              "disbursed_on": disbursed, "maturity_on": _add_months(disbursed, term),
                              "repayments": reps}, None, commit=False)
            out[r["loan_id"]] = b.id
        db.commit()
    logger.info("loan book: %s loans", len(out))
    return out


def seed_owner_business(root: Path, owner_user_id: int) -> int:
    """The owner surface's business (Navro'z Tekstil) bound to owner@converza.uz."""
    c = _truth(root / "hero_navroz")["company"]
    with get_db_context() as db:
        b = BorrowerService(db).upsert_borrower({"name": c["name"], "stir": c["stir"], "industry": c.get("industry", ""),
                                                 "region": c.get("region", ""), "employees": c.get("employees"),
                                                 "owner_user_id": owner_user_id}, None)
        return b.id


# ------------------------------------------------------------------------------------------- uploads

def upload_borrower_files(borrower_id: int, files: list[Path], owner_kind: str = "bank") -> int:
    """Uploads files not yet stored for this borrower (by sha256). Returns how many were queued."""
    queued = 0
    with get_db_context() as db:
        have = set(db.scalars(select(Document.sha256).where(Document.borrower_id == borrower_id,
                                                            Document.owner_kind == owner_kind)).all())
        for f in files:
            content = f.read_bytes()
            if sha256(content) in have:
                continue
            DocumentService(db).upload(content, f.name, owner_kind=owner_kind, borrower_id=borrower_id, actor=None)
            queued += 1
    return queued


def seed_application(number: str, folder: Path, row: dict) -> int:
    t = _truth(folder)
    c = t.get("company") or {}
    queued = 0
    with get_db_context() as db:
        s = ApplicationService(db)
        app = db.scalars(select(Application).where(Application.number == number)).first()
        if app is None:
            app = s.create_application({
                "borrower": {"name": c.get("name") or row["name"], "stir": c["stir"],
                             "industry": c.get("industry") or row.get("industry", ""), "region": c.get("region", ""),
                             "employees": c.get("employees"), "since": c.get("since")},
                "number": number, "requested_amount": _mln_to_k(row["requested_mln"]),
                "term_months": int(row["term_months"]), "received_on": date.fromisoformat(row["received"]),
            }, None)
        have = set(db.scalars(select(Document.sha256).join(ApplicationDocument,
                                                           ApplicationDocument.document_id == Document.id)
                              .where(ApplicationDocument.application_id == app.id)).all())
        for f in _files(folder):
            content = f.read_bytes()
            if sha256(content) in have:
                continue
            s.attach_upload(app, content, f.name, None)
            queued += 1
        if not queued and app.analysed_at is None:
            enqueue_analysis(db, app)   # resumed run: make sure the analysis is queued
            db.commit()
    return queued


# ------------------------------------------------------------------------------------------- waiting

def pending_jobs(kinds=("analyse_document", "analyse_application", "narrative")) -> int:
    with get_db_context() as db:
        return db.scalar(select(func.count(Job.id)).where(Job.kind.in_(kinds),
                                                          Job.status.in_(("queued", "running")))) or 0


def wait_for_documents(label: str, doc_filter=None, limit_s: int = WAIT_LIMIT_S) -> None:
    t0 = time.monotonic()
    last = None
    while time.monotonic() - t0 < limit_s:
        with get_db_context() as db:
            stmt = select(func.count(Document.id)).where(Document.status.in_(("queued", "processing")),
                                                         Document.owner_kind != "public")
            if doc_filter is not None:
                stmt = stmt.where(doc_filter)
            n = db.scalar(stmt) or 0
        jobs = pending_jobs() if doc_filter is None else 0
        if n == 0 and jobs == 0:
            logger.info("%s: done in %.0f s", label, time.monotonic() - t0)
            return
        if (n, jobs) != last or int(time.monotonic() - t0) % 30 == 0:
            logger.info("%s: %s documents and %s jobs pending (%.0f s)", label, n, jobs, time.monotonic() - t0)
            last = (n, jobs)
        time.sleep(3)
    logger.warning("%s: still pending after %s s; continuing", label, limit_s)


def run_monitoring(as_of: date, borrower_ids: list[int] | None = None, label: str = "monitoring") -> None:
    with get_db_context() as db:
        run, _job = start_run(db, None, as_of, borrower_ids)
        run_id = run.id
    t0 = time.monotonic()
    while time.monotonic() - t0 < WAIT_LIMIT_S:
        with get_db_context() as db:
            r = db.get(MonitoringRun, run_id)
            if r.status in ("done", "failed"):
                logger.info("%s as of %s: %s in %.0f s", label, as_of, r.status, time.monotonic() - t0)
                return
        time.sleep(3)


def _run_exists(as_of: date) -> bool:
    with get_db_context() as db:
        return db.scalars(select(MonitoringRun).where(MonitoringRun.as_of == as_of,
                                                      MonitoringRun.status == "done")).first() is not None


# ------------------------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="app.seed_demo")
    ap.add_argument("--no-wait", action="store_true", help="queue uploads and exit (no monitoring run)")
    ap.add_argument("--portfolio-limit", type=int, default=0, help="seed only the first N portfolio bundles")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    t_start = time.monotonic()
    root = seed_dir()
    users = seed_users()
    loan_borrowers = seed_loan_book(root)
    owner_bid = seed_owner_business(root, users["owner"])

    with open(root / "applications.csv", encoding="utf-8") as fh:
        app_rows = {r["id"]: r for r in csv.DictReader(fh)}

    # 1. Zilola's earlier quarter, then a monitoring run as of that quarter (Zilola only): a real history point
    zilola_dir = root / "hero_zilola"
    zilola_stir = _truth(zilola_dir)["company"]["stir"]
    with get_db_context() as db:
        zilola_bid = BorrowerService(db).by_stir(zilola_stir).id
    hist = zilola_dir / "history"
    if hist.is_dir():
        upload_borrower_files(zilola_bid, _files(hist))
        if not a.no_wait and not _run_exists(EARLIER_QUARTER_AS_OF):
            wait_for_documents("Zilola Q2", Document.borrower_id == zilola_bid)
            run_monitoring(EARLIER_QUARTER_AS_OF, [zilola_bid], "earlier-quarter monitoring (Zilola)")

    # 2. heroes: the loan file under review, Zilola's latest quarter, the owner's documents
    hero_app = next((n for n, r in app_rows.items() if r["bundle"] == "hero_farovon"), None)
    if hero_app:
        n = seed_application(hero_app, root / "hero_farovon", app_rows[hero_app])
        logger.info("%s: %s documents queued", hero_app, n)
    logger.info("Zilola Q3: %s documents queued", upload_borrower_files(zilola_bid, _files(zilola_dir)))
    logger.info("Navro'z (owner): %s documents queued",
                upload_borrower_files(owner_bid, _files(root / "hero_navroz"), owner_kind="owner"))

    # 3. the other applications in the queue
    for number, row in app_rows.items():
        if number == hero_app:
            continue
        n = seed_application(number, root / row["bundle"], row)
        logger.info("%s: %s documents queued", number, n)

    # 4. portfolio, by loan_id (Zilola comes from her hero bundle with history)
    port = root / "portfolio"
    loan_ids = sorted(p.name for p in port.iterdir() if p.is_dir()) if port.is_dir() else []
    if a.portfolio_limit:
        loan_ids = loan_ids[: a.portfolio_limit]
    queued = 0
    for loan_id in loan_ids:
        bid = loan_borrowers.get(loan_id)
        if bid is None or bid == zilola_bid:
            continue
        queued += upload_borrower_files(bid, _files(port / loan_id))
    logger.info("portfolio: %s documents queued for %s loans (%.0f s so far)", queued, len(loan_ids),
                time.monotonic() - t_start)

    if a.no_wait:
        return
    # 5. once everything is analysed: the portfolio monitoring run
    wait_for_documents("all documents")
    run_monitoring(utcnow().date(), None, "portfolio monitoring")
    logger.info("seed finished in %.0f s", time.monotonic() - t_start)


if __name__ == "__main__":
    main()
