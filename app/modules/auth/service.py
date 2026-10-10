from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.scopes import scopes_for
from app.core.security import (TokenError, create_access_token, create_refresh_token, verify_password,
                               verify_refresh_token)
from app.modules.users.models import User

DEMO_USERS = {
    "officer": {"email": "officer@converza.uz", "full_name": "G. Abdullayeva", "role": "officer"},
    "owner": {"email": "owner@converza.uz", "full_name": "S. Nazarov", "role": "owner"},
}


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _tokens(self, user: User) -> dict:
        scopes = scopes_for(user.role)
        return {
            "access_token": create_access_token(user_id=user.id, user_uuid=str(user.uuid), email=user.email,
                                                role=user.role, scopes=scopes),
            "refresh_token": create_refresh_token(user_id=user.id, user_uuid=str(user.uuid)),
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_MINUTES * 60,
            "user": user,
            "scopes": scopes,
        }

    def login(self, email: str, password: str) -> dict:
        user = self.db.scalars(select(User).where(func.lower(User.email) == email.strip().lower())).first()
        if user is None or not verify_password(password, user.password_hash):
            raise AppException(code="invalid_credentials", status_code=401, detail="Invalid email or password")
        if not user.is_active:
            raise AppException(code="user_disabled", status_code=403, detail="User is disabled")
        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(user)
        return self._tokens(user)

    def refresh(self, refresh_token: str) -> dict:
        try:
            claims = verify_refresh_token(refresh_token)
        except TokenError as exc:
            raise AppException(code="unauthorized", status_code=401, detail=str(exc))
        user = self.db.get(User, claims.user_id)
        if user is None or not user.is_active:
            raise AppException(code="unauthorized", status_code=401, detail="User not found or disabled")
        return self._tokens(user)

    def demo_login(self, role: str) -> dict:
        if not settings.DEMO_LOGIN_ENABLED:
            raise AppException(code="demo_login_disabled", status_code=403, detail="Demo login is disabled")
        user = ensure_demo_user(self.db, role)
        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(user)
        return self._tokens(user)


def ensure_demo_user(db: Session, role: str) -> User:
    """Idempotent: the demo users exist whenever demo login is enabled. Their password is random and unusable."""
    import secrets

    from app.core.security import hash_password

    spec = DEMO_USERS[role]
    user = db.scalars(select(User).where(User.email == spec["email"])).first()
    if user is None:
        user = User(email=spec["email"], full_name=spec["full_name"], role=spec["role"],
                    password_hash=hash_password(secrets.token_hex(24)), is_active=True)
        db.add(user)
        db.flush()
    return user
