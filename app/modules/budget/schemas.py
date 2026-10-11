from pydantic import BaseModel, Field, field_validator


class BudgetLineIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    category: str = Field(default="total", max_length=32)
    planned_income: float | None = Field(default=None, ge=0, le=1e15)     # UZS
    planned_spending: float | None = Field(default=None, ge=0, le=1e15)   # UZS

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        from app.pipeline.statements.categorise import CATEGORIES
        v = (v or "total").strip()
        if v != "total" and v not in CATEGORIES:
            raise ValueError("unknown category")
        return v


class BudgetPut(BaseModel):
    """Replaces the plan for every month named in `lines` (lines left out of those months are removed)."""
    lines: list[BudgetLineIn] = Field(default_factory=list, max_length=400)
