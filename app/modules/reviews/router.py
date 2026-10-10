from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.scopes import Scope
from app.modules.auth.deps import require_scope
from app.modules.extraction.service import FactSerializer
from app.modules.reviews.schemas import FactReviewCreate
from app.modules.reviews.service import ReviewService

router = APIRouter(prefix="/api/v1", tags=["reviews"])


@router.post("/facts/{fact_uuid}/review")
def review_fact(fact_uuid: UUID, data: FactReviewCreate, db: Session = Depends(get_db),
                actor=Depends(require_scope(Scope.FACT_REVIEW))):
    s = ReviewService(db)
    fact = s.review(s.fact_or_404(fact_uuid), data.model_dump(), actor)
    return FactSerializer(db).one(fact)
