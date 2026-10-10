from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PROJECT_NAME: str = "converza"
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "postgresql+psycopg2://app:app@localhost:5462/app"
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["*"])

    JWT_SECRET: str = Field(..., min_length=32)
    ACCESS_TOKEN_MINUTES: int = 60
    REFRESH_TOKEN_DAYS: int = 7

    SEED_ADMIN_EMAIL: str = ""
    SEED_ADMIN_PASSWORD: str = ""
    DEMO_LOGIN_ENABLED: bool = True      # POST /auth/demo issues tokens for the seeded demo users
    SEED_DEMO: bool = False              # read by app.seed_demo (track C)

    # worker / job queue
    WORKER_ENABLED: bool = True          # in-process worker in the API lifespan (dev); prod runs `python -m app.worker`
    WORKER_CONCURRENCY: int = 2
    WORKER_POLL_S: float = 0.5
    WORKER_STALE_LOCK_S: int = 300
    WORKER_HEARTBEAT_FILE: str = "/tmp/worker-heartbeat"

    # public /analyse path
    PUBLIC_DEADLINE_S: int = 55
    PUBLIC_RETENTION_HOURS: int = 24
    PUBLIC_MAX_UPLOAD_MB: int = 20
    PUBLIC_MAX_OCR_PAGES: int = 10
    BANK_MAX_UPLOAD_MB: int = 50
    BANK_MAX_OCR_PAGES: int = 40

    FILES_DIR: str = "./data/files"
    EVAL_RESULTS_DIR: str = "./eval/results"

    # LLM (only narrative, CFO Q&A, unmapped-line fallback)
    LLM_PROVIDER: str = "openai"         # openai | anthropic | ollama | none
    LLM_MODEL: str = "gpt-4.1-mini"
    LLM_BASE_URL: str = ""
    LLM_TIMEOUT_S: float = 20.0
    LLM_REDACT: bool = True
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # build / deploy metadata (GIT_SHA, BUILT_AT from build args; DEPLOYED_AT from the deploy shell)
    GIT_SHA: str = "dev"
    BUILT_AT: str = ""
    DEPLOYED_AT: str = ""


settings = Settings()
