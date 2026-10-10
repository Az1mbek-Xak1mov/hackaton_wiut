from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    return v


def snapshot(obj: Any, fields: Iterable[str]) -> dict:
    return {f: _jsonable(getattr(obj, f, None)) for f in fields}


def record(db: Session, actor: Any, action: str, entity: str, entity_uuid: UUID | None,
           before: dict | None = None, after: dict | None = None) -> AuditLog:
    """Adds a log line to the caller's session: the change and its log commit together.
    `actor` is a User, None ("system") or a string label such as "public"."""
    if actor is None:
        actor_id, actor_email = None, "system"
    elif isinstance(actor, str):
        actor_id, actor_email = None, actor
    else:
        actor_id, actor_email = actor.id, actor.email
    row = AuditLog(actor_user_id=actor_id, actor_email=actor_email, action=action, entity=entity,
                   entity_uuid=entity_uuid, before=before, after=after)
    db.add(row)
    return row


def list_stmt(entity: str | None = None, entity_uuid: UUID | None = None):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_uuid:
        stmt = stmt.where(AuditLog.entity_uuid == entity_uuid)
    return stmt
