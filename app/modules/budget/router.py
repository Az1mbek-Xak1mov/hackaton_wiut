from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.scopes import Scope
from app.modules.auth.deps import require_scope
from app.modules.budget.schemas import BudgetPut
from app.modules.budget.service import BudgetService

router = APIRouter(prefix="/api/v1/owner", tags=["owner-budget"])


@router.get("/budget")
def get_budget(db: Session = Depends(get_db), user=Depends(require_scope(Scope.OWNER_FILES))):
    """Plan vs actual per month (UZS). Actuals are pipeline facts: bank statement totals, else the cash-flow table."""
    return BudgetService(db).get(user)


@router.put("/budget")
def put_budget(data: BudgetPut, db: Session = Depends(get_db), user=Depends(require_scope(Scope.CFO_USE))):
    return BudgetService(db).put(user, [ln.model_dump() for ln in data.lines])


@router.get("/advice")
def get_advice(db: Session = Depends(get_db), user=Depends(require_scope(Scope.CFO_USE))):
    return BudgetService(db).latest_advice(user)


@router.post("/advice")
def post_advice(db: Session = Depends(get_db), user=Depends(require_scope(Scope.CFO_USE))):
    return BudgetService(db).generate_advice(user)
