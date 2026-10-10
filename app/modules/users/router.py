from fastapi import APIRouter, Depends
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.scopes import Scope
from app.modules.auth.deps import require_scope
from app.modules.auth.schemas import UserOut
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService

router = APIRouter(prefix="/api/v1", tags=["users"])


@router.get("/users", response_model=Page[UserOut])
def list_users(db: Session = Depends(get_db), _=Depends(require_scope(Scope.USER_READ))):
    return paginate(db, UserService(db).list_stmt())


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db), actor=Depends(require_scope(Scope.USER_WRITE))):
    return UserService(db).create_user(data.model_dump(), actor)
