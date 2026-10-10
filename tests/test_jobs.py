from app.modules.jobs.models import Job
from app.modules.jobs.service import JobService, claim_next, requeue_stale


def test_claim_never_returns_the_same_job_twice(db, session_factory):
    s = JobService(db)
    for i in range(3):
        s.enqueue("analyse_document", {"i": i}, ref=f"t:{i}")
    s.enqueue("analyse_document", {"public": True}, ref="t:public", priority=10)
    db.commit()
    claimed = []
    for _ in range(5):
        other = session_factory()
        jid = claim_next(other)
        other.close()
        if jid is not None:
            claimed.append(jid)
    assert len(claimed) == 4 and len(set(claimed)) == 4
    first = db.get(Job, claimed[0])
    assert first.payload == {"public": True}          # public job jumps the queue
    assert all(db.get(Job, j).status == "running" for j in claimed)


def test_stale_running_job_is_requeued(db):
    from datetime import timedelta

    from app.core.timeutil import utcnow
    job = JobService(db).enqueue("analyse_document", {}, ref="t:stale")
    job.status, job.locked_at, job.attempts = "running", utcnow() - timedelta(hours=1), 1
    db.commit()
    assert requeue_stale(db) == 1
    db.refresh(job)
    assert job.status == "queued"


def test_skip_locked_on_postgres_with_two_workers():
    """3 jobs, 2 concurrent claimers on real Postgres: every job claimed exactly once.
    Runs when TEST_PG_URL points at a scratch database (e.g. the local compose db)."""
    import os
    import threading

    import pytest
    from sqlalchemy import create_engine, delete
    from sqlalchemy.orm import sessionmaker

    url = os.environ.get("TEST_PG_URL")
    if not url:
        pytest.skip("TEST_PG_URL not set")
    eng = create_engine(url)
    from app.models import Base
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    with Session() as s:
        s.execute(delete(Job).where(Job.ref.like("pgtest:%")))
        s.commit()
        for i in range(3):
            JobService(s).enqueue("noop", {"i": i}, ref=f"pgtest:{i}")
        s.commit()
    claimed: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        while True:
            with Session() as s:
                jid = claim_next(s)
            if jid is None:
                return
            with Session() as s:   # only our test jobs count
                if not s.get(Job, jid).ref.startswith("pgtest:"):
                    continue
            with lock:
                claimed.append(jid)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(claimed) == 3 and len(set(claimed)) == 3
    with Session() as s:
        s.execute(delete(Job).where(Job.ref.like("pgtest:%")))
        s.commit()
    eng.dispose()
