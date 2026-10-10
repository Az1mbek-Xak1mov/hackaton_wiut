from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import DemoLoginRequest, MeResponse, RefreshRequest, TokenResponse
from app.modules.auth.service import AuthService
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    return AuthService(db).login(form.username, form.password)


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    return AuthService(db).refresh(data.refresh_token)


@router.post("/demo", response_model=TokenResponse)
def demo_login(data: DemoLoginRequest, db: Session = Depends(get_db)):
    return AuthService(db).demo_login(data.role)


@router.get("/me", response_model=MeResponse)
def me(request: Request, user: User = Depends(get_current_user)):
    return {"user": user, "scopes": sorted(getattr(request.state, "scopes", set()))}
