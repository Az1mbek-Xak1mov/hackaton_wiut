from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.jobs.schemas import JobOut
from app.modules.jobs.service import JobService

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.get("/jobs/{job_uuid}", response_model=JobOut)
def get_job(job_uuid: UUID, db: Session = Depends(get_db)):
    # Job status carries no document content; the uuid is unguessable. Public /analyse polls it too.
    return JobService(db).job_or_404(job_uuid)
