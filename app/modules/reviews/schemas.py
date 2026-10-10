from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FactReviewCreate(BaseModel):
    action: Literal["verify", "correct", "flag"]
    value: float | None = None
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _value_for_correct(self):
        if self.action == "correct" and self.value is None:
            raise ValueError("value is required to correct a fact")
        return self
