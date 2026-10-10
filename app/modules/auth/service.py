from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.scopes import SURFACE_ROLES, scopes_for
from app.core.security import (TokenError, create_access_token, create_refresh_token, verify_password,
                               verify_refresh_token)
from app.modules.users.models import User

SURFACE_HINT = {
    "owner": "This is a bank officer account; sign in at app.converza.uz",
    "bank": "This is a business-owner account; sign in at converza.uz",
}
USER_FIELDS = ("email", "full_name", "role")

DEMO_USERS = {
    "officer": {"email": "officer@converza.uz", "full_name": "G. Abdullayeva", "role": "officer"},
    "owner": {"email": "owner@converza.uz", "full_name": "S. Nazarov", "role": "owner"},
}


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _tokens(self, user: User, surface: str) -> dict:
        scopes = scopes_for(user.role)
        return {
            "access_token": create_access_token(user_id=user.id, user_uuid=str(user.uuid), email=user.email,
                                                role=user.role, scopes=scopes, surface=surface),
            "refresh_token": create_refresh_token(user_id=user.id, user_uuid=str(user.uuid), surface=surface),
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_MINUTES * 60,
            "user": user,
            "scopes": scopes,
            "surface": surface,
        }

    @staticmethod
    def _check_surface(user: User, surface: str) -> None:
        if user.role not in SURFACE_ROLES.get(surface, set()):
            raise AppException(code="wrong_surface", status_code=403, detail=SURFACE_HINT[surface],
                               params={"surface": surface, "role": user.role})

    def login(self, email: str, password: str, surface: str = "owner") -> dict:
        user = self.db.scalars(select(User).where(func.lower(User.email) == email.strip().lower())).first()
        if user is None or not verify_password(password, user.password_hash):
            raise AppException(code="invalid_credentials", status_code=401, detail="Invalid email or password")
        if not user.is_active:
            raise AppException(code="user_disabled", status_code=403, detail="User is disabled")
        self._check_surface(user, surface)
        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(user)
        return self._tokens(user, surface)

    def refresh(self, refresh_token: str) -> dict:
        try:
            claims = verify_refresh_token(refresh_token)
        except TokenError as exc:
            raise AppException(code="unauthorized", status_code=401, detail=str(exc))
        user = self.db.get(User, claims.user_id)
        if user is None or not user.is_active:
            raise AppException(code="unauthorized", status_code=401, detail="User not found or disabled")
        self._check_surface(user, claims.surface)
        return self._tokens(user, claims.surface)

    def register(self, data: dict) -> dict:
        """Business-owner self sign-up: user (role owner) + their business (Borrower), then the token pair.
        No e-mail verification in this build: the address is stored as given."""
        from app.core.exceptions import ConflictError
        from app.core.security import hash_password
        from app.modules.audit import service as audit
        from app.modules.borrowers.models import Borrower

        email = data["email"].strip().lower()
        if self.db.scalars(select(User).where(func.lower(User.email) == email)).first():
            raise ConflictError("email_taken", f"An account with {email} already exists")
        borrower = None
        if data.get("stir"):
            borrower = self.db.scalars(select(Borrower).where(Borrower.stir == data["stir"])).first()
            if borrower is not None and borrower.owner_user_id is not None:
                raise ConflictError("stir_taken", "This STIR is already registered by another account")
        user = User(email=email, full_name=data["full_name"].strip(), role="owner",
                    password_hash=hash_password(data["password"]), is_active=True)
        self.db.add(user)
        self.db.flush()
        if borrower is None:
            borrower = Borrower(name=data["company_name"].strip(), stir=data.get("stir") or None,
                                industry=data.get("industry") or "", region=data.get("region") or "",
                                is_synthetic=False)
            self.db.add(borrower)
        borrower.owner_user_id = user.id
        self.db.flush()
        audit.record(self.db, user, "register", "user", user.uuid,
                     after=audit.snapshot(user, USER_FIELDS) | {"company": borrower.name, "stir": borrower.stir})
        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(user)
        return self._tokens(user, "owner")

    def demo_login(self, role: str) -> dict:
        if not settings.DEMO_LOGIN_ENABLED:
            raise AppException(code="not_found", status_code=404, detail="Not found")
        user = ensure_demo_user(self.db, role)
        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(user)
        return self._tokens(user, "owner" if role == "owner" else "bank")


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
