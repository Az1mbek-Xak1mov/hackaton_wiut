from fastapi import APIRouter, Depends

from app.core.exceptions import AppException
from app.core.scopes import Scope
from app.modules.auth.deps import require_scope

router = APIRouter(prefix="/api/v1/cfo", tags=["cfo"])


def _not_yet():
    raise AppException(code="not_implemented", status_code=501, detail="AI CFO Q&A is not available in this build yet")


@router.post("/messages")
def ask(_=Depends(require_scope(Scope.CFO_USE))):
    _not_yet()


@router.get("/messages")
def history(_=Depends(require_scope(Scope.CFO_USE))):
    _not_yet()
