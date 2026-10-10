from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.schemas import Email


class UserCreate(BaseModel):
    email: Email
    full_name: str = Field(default="", max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "officer", "owner", "demo_viewer"] = "officer"

    @field_validator("email")
    @classmethod
    def _norm(cls, v: str) -> str:
        return v.strip().lower()
