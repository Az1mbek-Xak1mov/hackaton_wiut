from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.scopes import Scope
from app.modules.applications.service import ApplicationService
from app.modules.auth.deps import require_scope
from app.modules.extraction.models import Fact
from app.modules.extraction.service import FactSerializer

router = APIRouter(prefix="/api/v1", tags=["ratios"])


@router.get("/applications/{ref}/ratios")
def application_ratios(ref: str, db: Session = Depends(get_db), _=Depends(require_scope(Scope.APPLICATION_READ))):
    app = ApplicationService(db).app_or_404(ref)
    rows = db.scalars(select(Fact).where(Fact.application_id == app.id, Fact.kind == "computed")
                      .order_by(Fact.id)).all()
    return {"facts": FactSerializer(db).many(rows)}
