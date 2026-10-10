from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    uuid: UUID
    email: str
    full_name: str
    role: str
    is_active: bool


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
    scopes: list[str]


class RefreshRequest(BaseModel):
    refresh_token: str


class DemoLoginRequest(BaseModel):
    role: Literal["officer", "owner"]


class MeResponse(BaseModel):
    user: UserOut
    scopes: list[str]
