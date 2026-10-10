from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    uuid: UUID
    created_at: datetime
    actor_email: str
    action: str
    entity: str
    entity_uuid: UUID | None
    before: dict | None
    after: dict | None
