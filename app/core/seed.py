"""Idempotent start-up seed: first admin, the two named accounts (owner, officer), default settings rows.

No borrowers, applications or documents are created here (only `python -m app.seed_demo` does that, with
SEED_DEMO=true). The owner account gets its own business row, as a self sign-up would."""
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
        seed_named_users(db)
        if settings.DEMO_LOGIN_ENABLED:
            for role in DEMO_USERS:
                ensure_demo_user(db, role)
        if db.scalars(select(AppSetting).where(AppSetting.key == LLM_KEY)).first() is None:
            db.add(AppSetting(key=LLM_KEY, value={"enabled": True}))
        db.commit()


SEED_OWNER = {"email": "owner@converza.uz", "full_name": "Farovon Savdo owner", "company": "Farovon Savdo MChJ",
              "stir": "302447118", "industry": "Food distribution", "region": "Tashkent"}
SEED_OFFICER = {"email": "officer@converza.uz", "full_name": "G. Abdullayeva"}


def seed_named_users(db) -> None:
    """owner@converza.uz (password SEED_OWNER_PASSWORD) with its business, officer@converza.uz
    (SEED_OFFICER_PASSWORD). Created only when absent; an existing password is never changed."""
    from app.modules.borrowers.models import Borrower
    from app.modules.users.models import User

    if settings.SEED_OWNER_PASSWORD:
        owner = db.scalars(select(User).where(User.email == SEED_OWNER["email"])).first()
        if owner is None:
            owner = User(email=SEED_OWNER["email"], full_name=SEED_OWNER["full_name"], role="owner",
                         password_hash=hash_password(settings.SEED_OWNER_PASSWORD), is_active=True)
            db.add(owner)
            db.flush()
            logger.info("seeded owner %s", owner.email)
        if db.scalars(select(Borrower).where(Borrower.owner_user_id == owner.id)).first() is None:
            b = db.scalars(select(Borrower).where(Borrower.stir == SEED_OWNER["stir"])).first()
            if b is None:
                b = Borrower(name=SEED_OWNER["company"], stir=SEED_OWNER["stir"], industry=SEED_OWNER["industry"],
                             region=SEED_OWNER["region"], is_synthetic=False)
                db.add(b)
            b.owner_user_id = owner.id
            db.flush()
    if settings.SEED_OFFICER_PASSWORD:
        if db.scalars(select(User).where(User.email == SEED_OFFICER["email"])).first() is None:
            db.add(User(email=SEED_OFFICER["email"], full_name=SEED_OFFICER["full_name"], role="officer",
                        password_hash=hash_password(settings.SEED_OFFICER_PASSWORD), is_active=True))
            db.flush()
            logger.info("seeded officer %s", SEED_OFFICER["email"])
