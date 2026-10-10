from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.exceptions import AppException
from app.core.scopes import Role, Scope
from app.core.security import TokenError, verify_access_token
from app.modules.users.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _user_from_token(request: Request, token: str, db: Session) -> User:
    try:
        claims = verify_access_token(token)
    except TokenError as exc:
        raise AppException(code="unauthorized", status_code=401, detail=str(exc))
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise AppException(code="unauthorized", status_code=401, detail="User not found or disabled")
    request.state.scopes = set(claims.scopes)
    return user


def get_current_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return _user_from_token(request, token, db)


def get_optional_user(request: Request, token: str | None = Depends(oauth2_optional),
                      db: Session = Depends(get_db)) -> User | None:
    """For endpoints that serve public documents to anyone and bank documents to signed-in users.
    Also accepts `?token=` because <img src> cannot send headers."""
    token = token or request.query_params.get("token")
    if not token:
        return None
    return _user_from_token(request, token, db)


def has_scope(request: Request, user: User | None, scope: Scope) -> bool:
    if user is None:
        return False
    if user.role == Role.ADMIN.value:
        return True
    return scope.value in getattr(request.state, "scopes", set())


def require_scope(*required: Scope):
    """Passes if the token has ANY of `required`. Admins pass every check."""
    def dependency(request: Request, user: User = Depends(get_current_user)) -> User:
        if user.role == Role.ADMIN.value:
            return user
        needed = {s.value for s in required}
        if not needed & getattr(request.state, "scopes", set()):
            raise AppException(code="forbidden", status_code=403,
                               detail=f"Missing scope. Need one of {sorted(needed)}")
        return user
    return dependency
