from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.scopes import Scope
from app.modules.auth.deps import require_scope
from app.modules.cfo.service import CfoService

router = APIRouter(prefix="/api/v1/cfo", tags=["cfo"])


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


@router.post("/messages")
def ask(data: Question, db: Session = Depends(get_db), user=Depends(require_scope(Scope.CFO_USE))):
    return CfoService(db).ask(user, data.question)


@router.get("/messages")
def history(db: Session = Depends(get_db), user=Depends(require_scope(Scope.CFO_USE))):
    return CfoService(db).history(user)
