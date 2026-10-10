from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.schemas import Email, Stir


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
    surface: str


class RegisterRequest(BaseModel):
    email: Email
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=255)
    stir: Stir | None = None
    industry: str = Field(default="", max_length=128)
    region: str = Field(default="", max_length=128)

    @field_validator("stir", mode="before")
    @classmethod
    def _blank_stir(cls, v):
        return (v or "").replace(" ", "") or None


class RefreshRequest(BaseModel):
    refresh_token: str


class DemoLoginRequest(BaseModel):
    role: Literal["officer", "owner"]


class MeResponse(BaseModel):
    user: UserOut
    scopes: list[str]
