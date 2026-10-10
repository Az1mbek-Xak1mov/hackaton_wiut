from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.exceptions import AppException
from app.modules.analyse.bundle import MAX_FILE_MB, MAX_FILES, MAX_TOTAL_MB, MB, BundleService, Item
from app.modules.analyse.service import AnalyseService

router = APIRouter(prefix="/api/v1", tags=["analyse"])


@router.post("/analyse", status_code=201)
def analyse(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Public, no auth (rate-limited by nginx). Reads at most PUBLIC_MAX_UPLOAD_MB + 1 byte.
    A ZIP is answered as a loan file (`kind: "bundle"`, see /analyse/bundle)."""
    content = file.file.read(settings.PUBLIC_MAX_UPLOAD_MB * 1024 * 1024 + 1)
    return AnalyseService(db).submit(content, file.filename or "upload")


@router.post("/analyse/bundle", status_code=201)
def analyse_bundle(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    """Public loan-file check: several files and/or ZIP archives analysed together (cross-document rules,
    ratios, verified summary). Caps: 12 analysed files, 20 MB each, 40 MB in total; read with hard limits."""
    if len(files) > MAX_FILES * 2:
        raise AppException(code="too_many_files", status_code=422,
                           detail=f"Upload at most {MAX_FILES} files (or one ZIP)", params={"max_files": MAX_FILES})
    items, total = [], 0
    for f in files:
        content = f.file.read(MAX_TOTAL_MB * MB + 1)
        name = f.filename or "upload"
        total += len(content)
        if total > MAX_TOTAL_MB * MB:
            raise AppException(code="bundle_too_large", status_code=413,
                               detail=f"The files are larger than {MAX_TOTAL_MB} MB together",
                               params={"max_mb": MAX_TOTAL_MB})
        if len(content) > MAX_FILE_MB * MB and not name.lower().endswith(".zip"):
            raise AppException(code="file_too_large", status_code=413,
                               detail=f"{name} is larger than {MAX_FILE_MB} MB", params={"max_mb": MAX_FILE_MB})
        items.append(Item(name, content))
    return BundleService(db).submit(items)


@router.get("/analyse/bundle/{bundle_uuid}")
def analyse_bundle_result(bundle_uuid: UUID, db: Session = Depends(get_db)):
    s = BundleService(db)
    return s.result(s.bundle_or_404(bundle_uuid))


@router.get("/analyse/{doc_uuid}")
def analyse_result(doc_uuid: UUID, db: Session = Depends(get_db)):
    s = AnalyseService(db)
    return s.result(s.public_doc_or_404(doc_uuid))
