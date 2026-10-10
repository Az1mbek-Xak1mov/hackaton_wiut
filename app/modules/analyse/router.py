from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.modules.analyse.service import AnalyseService

router = APIRouter(prefix="/api/v1", tags=["analyse"])


@router.post("/analyse", status_code=201)
def analyse(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Public, no auth (rate-limited by nginx). Reads at most PUBLIC_MAX_UPLOAD_MB + 1 byte."""
    content = file.file.read(settings.PUBLIC_MAX_UPLOAD_MB * 1024 * 1024 + 1)
    return AnalyseService(db).submit(content, file.filename or "upload")


@router.get("/analyse/{doc_uuid}")
def analyse_result(doc_uuid: UUID, db: Session = Depends(get_db)):
    s = AnalyseService(db)
    return s.result(s.public_doc_or_404(doc_uuid))
