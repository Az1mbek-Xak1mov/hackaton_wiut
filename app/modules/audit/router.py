from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.scopes import Scope
from app.modules.audit import service as audit
from app.modules.audit.schemas import AuditResponse
from app.modules.auth.deps import require_scope

router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get("/audit", response_model=Page[AuditResponse])
def list_audit(entity: str | None = None, entity_uuid: UUID | None = None, db: Session = Depends(get_db),
               _=Depends(require_scope(Scope.AUDIT_READ))):
    return paginate(db, audit.list_stmt(entity, entity_uuid))
