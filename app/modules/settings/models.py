from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class AppSetting(BaseModel):
    """Runtime switches changed from the UI (e.g. `llm_enabled`). Audited by the service."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
