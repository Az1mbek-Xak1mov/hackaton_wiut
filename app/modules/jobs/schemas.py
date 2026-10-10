from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    uuid: UUID
    kind: str
    status: str
    stage: str
    progress: int
    error: str
    stage_timings: dict
