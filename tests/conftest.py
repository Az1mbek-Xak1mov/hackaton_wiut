import os
import secrets
import tempfile

os.environ.update({
    "JWT_SECRET": secrets.token_hex(32),
    "DATABASE_URL": "sqlite://",
    "SEED_ADMIN_EMAIL": "", "SEED_ADMIN_PASSWORD": "",
    "WORKER_ENABLED": "false",
    "DEMO_LOGIN_ENABLED": "true",
    "FILES_DIR": tempfile.mkdtemp(prefix="converza-files-"),
    "EVAL_RESULTS_DIR": tempfile.mkdtemp(prefix="converza-eval-"),
    "OPENAI_API_KEY": "",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.core.db as core_db  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.modules.users.models import User  # noqa: E402


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine, monkeypatch):
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    # the runner, seed and worker open their own sessions through get_db_context → same in-memory DB
    monkeypatch.setattr(core_db, "SessionLocal", factory)
    return factory


@pytest.fixture()
def db(session_factory):
    s = session_factory()
    yield s
    s.close()


@pytest.fixture()
def client(db, session_factory):
    def _get_db():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_user(db, email: str, role: str, password: str = "password123") -> User:
    u = User(email=email, full_name=email.split("@")[0], role=role, password_hash=hash_password(password),
             is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def auth(client, email: str, password: str = "password123", surface: str = "bank") -> dict:
    r = client.post(f"/api/v1/auth/login?surface={surface}", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def demo_auth(client, role: str = "officer") -> dict:
    r = client.post("/api/v1/auth/demo", json={"role": role})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
