import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.timeutil import aware, utcnow
from app.modules.jobs.models import Job

logger = logging.getLogger(__name__)

PUBLIC_PRIORITY = 10
MAX_ATTEMPTS = 2


class JobService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def enqueue(self, kind: str, payload: dict, *, ref: str = "", priority: int = 0,
                deadline_at: datetime | None = None, run_after: datetime | None = None) -> Job:
        """Adds the job to the caller's transaction (enqueue together with the row it works on)."""
        job = Job(kind=kind, payload=payload, ref=ref, priority=priority, deadline_at=deadline_at, run_after=run_after,
                  stage_timings={})
        self.db.add(job)
        self.db.flush()
        return job

    def job_or_404(self, job_uuid: UUID) -> Job:
        job = self.db.scalars(select(Job).where(Job.uuid == job_uuid)).first()
        if job is None:
            raise NotFoundError("job")
        return job

    def latest_for(self, ref: str) -> Job | None:
        return self.db.scalars(select(Job).where(Job.ref == ref).order_by(Job.id.desc())).first()

    def pending_for(self, ref: str, kind: str) -> Job | None:
        return self.db.scalars(select(Job).where(Job.ref == ref, Job.kind == kind,
                                                 Job.status.in_(("queued", "running")))).first()


def claim_next(db: Session) -> int | None:
    """Claims one queued job. On Postgres `FOR UPDATE SKIP LOCKED` lets several workers poll safely;
    public jobs (priority 10) jump the queue."""
    now = utcnow()
    stmt = (select(Job)
            .where(Job.status == "queued", or_(Job.run_after.is_(None), Job.run_after <= now))
            .order_by(Job.priority.desc(), Job.id)
            .limit(1)
            .with_for_update(skip_locked=True))
    job = db.scalars(stmt).first()
    if job is None:
        db.rollback()
        return None
    job.status = "running"
    job.locked_at = now
    job.started_at = job.started_at or now
    job.attempts = (job.attempts or 0) + 1
    db.commit()
    return job.id


def requeue_stale(db: Session) -> int:
    """A `running` job whose lock was not refreshed for WORKER_STALE_LOCK_S belonged to a dead worker."""
    cutoff = utcnow() - timedelta(seconds=settings.WORKER_STALE_LOCK_S)
    stale = db.scalars(select(Job).where(Job.status == "running", Job.locked_at < cutoff)
                       .with_for_update(skip_locked=True)).all()
    for job in stale:
        if (job.attempts or 0) < MAX_ATTEMPTS:
            job.status = "queued"
            job.locked_at = None
            logger.warning("requeued stale job %s (%s)", job.id, job.kind)
        else:
            job.status = "failed"
            job.error = "worker lost the job twice (stale lock)"
            job.finished_at = utcnow()
    db.commit()
    return len(stale)


def past_deadline(job: Job) -> bool:
    return job.deadline_at is not None and utcnow() >= aware(job.deadline_at)
