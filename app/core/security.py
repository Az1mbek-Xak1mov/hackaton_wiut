from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import settings

ALGORITHM = "HS256"
_hasher = PasswordHash((Argon2Hasher(),))


class TokenError(Exception):
    """Expired, malformed, wrongly signed or of the wrong type."""


@dataclass
class TokenClaims:
    user_id: int
    scopes: list[str]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password, password_hash)
    except Exception:
        return False


def _encode(payload: dict, token_type: str, expires: timedelta) -> str:
    now = datetime.now(timezone.utc)
    claims = payload | {"token_type": token_type, "iat": now, "exp": now + expires}
    return jwt.encode(claims, settings.JWT_SECRET, algorithm=ALGORITHM)


def _decode(token: str, token_type: str) -> TokenClaims:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM],
                             options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise TokenError("Token expired")
    except jwt.InvalidTokenError:
        raise TokenError("Invalid token")
    if payload.get("token_type") != token_type:
        raise TokenError("Invalid token type")
    return TokenClaims(user_id=int(payload["sub"]), scopes=list(payload.get("scopes") or []))


def create_access_token(*, user_id: int, user_uuid: str, email: str, role: str, scopes: list[str]) -> str:
    return _encode({"sub": str(user_id), "user_uuid": user_uuid, "email": email, "role": role, "scopes": scopes},
                   "access", timedelta(minutes=settings.ACCESS_TOKEN_MINUTES))


def create_refresh_token(*, user_id: int, user_uuid: str) -> str:
    return _encode({"sub": str(user_id), "user_uuid": user_uuid}, "refresh",
                   timedelta(days=settings.REFRESH_TOKEN_DAYS))


def verify_access_token(token: str) -> TokenClaims:
    return _decode(token, "access")


def verify_refresh_token(token: str) -> TokenClaims:
    return _decode(token, "refresh")
