from typing import Annotated, ClassVar, FrozenSet

from pydantic import BaseModel, Field, model_validator

Code = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")]
Name = Annotated[str, Field(min_length=1, max_length=255)]
Email = Annotated[str, Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
Stir = Annotated[str, Field(pattern=r"^[2-7]\d{8}$")]


class PatchModel(BaseModel):
    """Only fields that were sent are applied (`model_dump(exclude_unset=True)`).
    `null` means "clear this field" and is allowed only for fields in `nullable`."""
    nullable: ClassVar[FrozenSet[str]] = frozenset()

    @model_validator(mode="after")
    def _no_null_for_required(self):
        bad = sorted(f for f in self.model_fields_set if getattr(self, f) is None and f not in self.nullable)
        if bad:
            raise ValueError(f"{', '.join(bad)} cannot be null")
        return self
