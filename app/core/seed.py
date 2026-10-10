"""Idempotent start-up seed: first admin, demo users, default settings rows."""
import logging

from sqlalchemy import select, text

from app.core.config import settings
from app.core.db import get_db_context
from app.core.security import hash_password

logger = logging.getLogger(__name__)


def seed() -> None:
    from app.modules.auth.service import DEMO_USERS, ensure_demo_user
    from app.modules.settings.models import AppSetting
    from app.modules.settings.service import LLM_KEY
    from app.modules.users.models import User

    with get_db_context() as db:
        if db.get_bind().dialect.name == "postgresql":
            # uvicorn --workers 2 seeds from two processes at once: serialize, the second one finds the rows
            db.execute(text("SELECT pg_advisory_xact_lock(727274)"))
        if settings.SEED_ADMIN_EMAIL and settings.SEED_ADMIN_PASSWORD:
            if db.scalars(select(User).where(User.role == "admin")).first() is None:
                db.add(User(email=settings.SEED_ADMIN_EMAIL.strip().lower(), full_name="Administrator", role="admin",
                            password_hash=hash_password(settings.SEED_ADMIN_PASSWORD), is_active=True))
                logger.info("seeded first admin %s", settings.SEED_ADMIN_EMAIL)
        if settings.DEMO_LOGIN_ENABLED:
            for role in DEMO_USERS:
                ensure_demo_user(db, role)
        if db.scalars(select(AppSetting).where(AppSetting.key == LLM_KEY)).first() is None:
            db.add(AppSetting(key=LLM_KEY, value={"enabled": True}))
        db.commit()
