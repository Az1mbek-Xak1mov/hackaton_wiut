from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import DemoLoginRequest, MeResponse, RefreshRequest, RegisterRequest, TokenResponse
from app.modules.auth.service import AuthService
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), surface: Literal["owner", "bank"] = Query("owner"),
          db: Session = Depends(get_db)):
    """surface=owner (converza.uz) accepts owner accounts; surface=bank (app.converza.uz) officers/admins."""
    return AuthService(db).login(form.username, form.password, surface)


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    return AuthService(db).register(data.model_dump())


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    return AuthService(db).refresh(data.refresh_token)


@router.post("/demo", response_model=TokenResponse, include_in_schema=False)
def demo_login(data: DemoLoginRequest, db: Session = Depends(get_db)):
    return AuthService(db).demo_login(data.role)


@router.get("/me", response_model=MeResponse)
def me(request: Request, user: User = Depends(get_current_user)):
    return {"user": user, "scopes": sorted(getattr(request.state, "scopes", set()))}
