# Backend architecture (FastAPI + PostgreSQL + JWT)

A reusable blueprint for Python backend services. Copy the structure and
conventions into a new project and add your own domain modules. Examples use
a generic `projects → tasks` domain.

---

## 1. Stack

| Concern | Choice | Why |
|---|---|---|
| Web framework | FastAPI, sync route handlers | OpenAPI docs for free; sync keeps SQLAlchemy simple (FastAPI runs them in a threadpool) |
| ORM | SQLAlchemy 2.x with `Mapped[...]` typing | |
| Database | PostgreSQL 16 (`psycopg2-binary`) | |
| Migrations | Alembic, autogenerate + `compare_type=True` | |
| Validation / settings | Pydantic v2, `pydantic-settings` | |
| Auth | PyJWT (HS256) + `pwdlib[argon2]` | no auth server needed when the service issues and checks its own tokens |
| Pagination | `fastapi-pagination` (`Page[...]` + `paginate(db, stmt)`) | |
| Packaging | `uv` + `pyproject.toml` + `uv.lock`; Python pinned (`~=3.12.0`, `.python-version`) | reproducible; Docker build uses `uv sync --locked` |
| Tests | pytest + `TestClient`, SQLite in memory | the suite needs no running services |
| Runtime | Docker multi-stage image: `alembic upgrade head && uvicorn` | |

---

## 2. Directory layout

```
app/
  main.py                 # FastAPI app: lifespan, CORS, routers, exception handlers, /health
  core/                   # framework-level code, no business logic
    config.py             # Settings (env / .env), one `settings` instance
    db.py                 # engine, SessionLocal, get_db (per request), get_db_context (scripts/background)
    base_model.py         # Base + abstract BaseModel (id, uuid, created_at, updated_at)
    security.py           # password hashing, JWT encode/decode
    scopes.py             # Scope enum, Role enum, ROLE_SCOPES presets
    exceptions.py         # AppException + NotFound / Conflict / Upstream errors
    schemas.py            # shared field types (Code, Email…) and PatchModel
    seed.py               # idempotent start-up seed (first admin, default rows)
  models/__init__.py      # imports every model so Base.metadata is complete (Alembic, tests)
  modules/
    __init__.py           # ALL_ROUTERS list
    auth/                 # deps.py (guards), router, schemas, service
    users/                # models, schemas, service, router
    audit/                # models, schemas, service, router
    <feature>/
      models.py           # SQLAlchemy tables
      schemas.py          # Pydantic request/response models + all input validation
      service.py          # business logic, queries, commits, audit
      router.py           # HTTP layer: path, auth guard, call service, response_model
      client.py           # (only if it calls another service over HTTP)
  alembic/
    env.py                # URL from settings, target_metadata = app.models.Base.metadata
    versions/
tests/
  conftest.py             # env before imports, DB fixture, auth helpers, fakes
  test_<feature>.py
alembic.ini
Dockerfile
docker-compose.yml        # `db` always; `api` under profile `full`
pyproject.toml / uv.lock / .python-version
.env.example              # every setting, commented; the real .env is git-ignored
```

**Modular by feature, not by layer:** everything about one feature lives in
`app/modules/<feature>/`. A module may import another module's models and
services (e.g. `users.models.User`, `audit.service`), but `core/` never imports
from `modules/` (except `seed.py`, which creates initial rows).

---

## 3. Layers and their rules

```
HTTP request
  └─ router.py       path/query params, auth via Depends, call ONE service method, return
       └─ schemas.py    validates the body before the router runs (422 on bad input)
       └─ service.py    business rules, uniqueness checks, audit, commit; raises AppException
            └─ models.py   tables
            └─ client.py   other services over HTTP; raises UpstreamError
```

### Router — thin

No queries, no business `if`s.

```python
router = APIRouter(prefix="/api/v1", tags=["projects"])

read = require_scope(Scope.PROJECT_READ)
write = require_scope(Scope.PROJECT_WRITE)


@router.patch("/projects/{project_uuid}", response_model=ProjectResponse)
def update_project(project_uuid: UUID, data: ProjectUpdate, db: Session = Depends(get_db), actor: User = Depends(write)):
    s = ProjectService(db)
    return s.update_project(s.project_or_404(project_uuid), data.model_dump(exclude_unset=True), actor)
```

### Schema — all input validation

Lengths, regex patterns, enums (`Literal`), timezones, "cannot be null".
Services assume input is already well-formed. Response models use
`ConfigDict(from_attributes=True)` and are returned straight from ORM objects.

```python
Code = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")]
Name = Annotated[str, Field(min_length=1, max_length=255)]

class ProjectCreate(BaseModel):
    name: Name
    code: Code
    description: str = ""

class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    uuid: UUID
    name: str
    code: str
```

### Service — business logic

A class that takes the session (and any clients) in `__init__`:

```python
class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def project_or_404(self, project_uuid: UUID) -> Project:
        obj = self.db.scalars(select(Project).where(Project.uuid == project_uuid)).first()
        if obj is None:
            raise NotFoundError("project")
        return obj

    def create_project(self, data: dict, actor: User) -> Project:
        self._unique_code(data["code"])
        project = Project(**data)
        self.db.add(project)
        self.db.flush()                                   # assigns id/uuid
        audit.record(self.db, actor, "create", "project", project.uuid,
                     after=audit.snapshot(project, PROJECT_FIELDS))
        self.db.commit()
        self.db.refresh(project)
        return project
```

- Owns the transaction: `add` → `flush` → `audit.record` → `commit` → `refresh`.
- Takes plain `dict`s (`model_dump()`), never FastAPI objects; knows nothing about HTTP.
- Business invariants live here ("keep at least one active admin", "can't
  demote yourself", "a task moves only within its project").
- Raises `AppException` subclasses, never `HTTPException`.
- List endpoints: the service returns a `select()` (`list_stmt(...)`), the router paginates it.

### Model — tables

Inherits `BaseModel`. Constraints (`unique`, `UniqueConstraint`, FK `ondelete`)
are declared on the model so the DB is the last line of defence.

---

## 4. Configuration

One `Settings(BaseSettings)` in `app/core/config.py`, read from env / `.env`,
exposed as `settings`.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PROJECT_NAME: str = "my-service"
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "postgresql+psycopg2://app:app@localhost:5432/app"
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["*"])

    JWT_SECRET: str = Field(..., min_length=32)   # required: the app refuses to start without it
    ACCESS_TOKEN_MINUTES: int = 60
    REFRESH_TOKEN_DAYS: int = 7

    SEED_ADMIN_EMAIL: str = ""
    SEED_ADMIN_PASSWORD: str = ""

settings = Settings()
```

- Secrets that must exist are **required with no default**.
- Each external service = a URL + a key + a timeout. Optional ones default to an
  empty key; the client then answers "not configured" instead of crashing at start-up.
- Feature switches for background work (`<X>_ENABLED`) so tests and scripts can turn it off.
- `.env.example` lists every setting with a comment on what it is and where to get it.

---

## 5. PostgreSQL and the data model

### Base model

```python
Base = declarative_base()

class BaseModel(Base):
    __abstract__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)  # internal
    uuid: Mapped[UUID] = mapped_column(Uuid, default=uuid4, unique=True, nullable=False)           # public
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now(), onupdate=func.now())
```

Rules:
- **The int `id` never leaves the backend.** URLs and responses use `uuid`; FKs and joins use `id`.
- Timestamps are `timezone=True`, always UTC (`datetime.now(timezone.utc)`).
- `Uuid` is portable: native `UUID` on Postgres, still works on SQLite in tests.
- Enum-like values are short `String` columns validated by Pydantic (`Literal` / `Enum`);
  no DB enum types, so a new value needs no migration.
- Free-form structured data in `JSON` columns.
- Parent → children: `ForeignKey(..., ondelete="CASCADE")` +
  `relationship(back_populates=..., cascade="all, delete-orphan", order_by=...)`.
- Optional references to users (`created_by`, audit actor): `ondelete="SET NULL"`.
- Scoped uniqueness with named constraints:
  `UniqueConstraint("project_id", "code", name="uq_task_project_code")`.
- Load trees with `selectinload(...)` chains; avoid lazy loads inside loops.

```python
class Project(BaseModel):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    tasks: Mapped[List["Task"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="(Task.position, Task.code)")

class Task(BaseModel):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_task_project_code"),)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    project: Mapped[Project] = relationship(back_populates="tasks")
```

### Sessions

```python
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def get_db():                    # one session per request, via Depends
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()               # anything not committed is rolled back

@contextmanager
def get_db_context():            # same, for seed / background tasks / WebSockets
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

Code that keeps ORM objects after closing its session loads them fully and
calls `db.expunge_all()` first.

### Uniqueness: service check **and** DB constraint

The service checks first to return a precise error
(`ConflictError("project_code_taken", ...)`). Two concurrent requests can
both pass that check; the DB constraint then fails, and a global handler turns
`IntegrityError` into a generic `409 conflict`. Keep both.

### Migrations (Alembic)

- `alembic/env.py` sets the URL from `settings.DATABASE_URL` and uses
  `app.models.Base.metadata`. **Add every new model to `app/models/__init__.py`**
  or autogenerate won't see it.
- `compare_type=True` in both online and offline mode.
- Workflow: change models → `uv run alembic revision --autogenerate -m "..."` →
  **read and fix the generated file** → `uv run alembic upgrade head`.
- The container runs `alembic upgrade head` before starting uvicorn.
- Tests don't run migrations: `Base.metadata.create_all()` on SQLite.

### Local Postgres (docker-compose)

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-app}
      POSTGRES_DB: app
    ports: ["5462:5432"]            # non-default host port avoids clashes
    volumes: [app-db:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app"]
      interval: 5s
      retries: 10
  api:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg2://app:${POSTGRES_PASSWORD:-app}@db:5432/app
    depends_on: { db: { condition: service_healthy } }
    profiles: [full]
```

`POSTGRES_PASSWORD` applies only when the volume is first created; change it
later with `ALTER USER ... PASSWORD`.

---

## 6. Authentication (JWT)

### Tokens — `app/core/security.py`

- HS256 signed with `settings.JWT_SECRET`. One symmetric secret is enough
  because this service is the only one that issues **and** verifies the tokens.
  (If other services must verify them, switch to RS256/ES256 with a public key.)
- Two token types, each carrying `token_type`; a refresh token is never
  accepted as an access token or the other way round.

| | Claims | Lifetime |
|---|---|---|
| access | `sub` (user id), `user_uuid`, `email`, `role`, `scopes`, `token_type="access"`, `iat`, `exp` | `ACCESS_TOKEN_MINUTES` (60) |
| refresh | `sub`, `user_uuid`, `token_type="refresh"`, `iat`, `exp` | `REFRESH_TOKEN_DAYS` (7) |

```python
ALGORITHM = "HS256"
_hasher = PasswordHash((Argon2Hasher(),))

class TokenError(Exception):
    """Expired, malformed, wrongly signed or of the wrong type."""

def _encode(payload: dict, token_type: str, expires: timedelta) -> str:
    now = datetime.now(timezone.utc)
    claims = payload | {"token_type": token_type, "iat": now, "exp": now + expires}
    return jwt.encode(claims, settings.JWT_SECRET, algorithm=ALGORITHM)

def _decode(token: str, token_type: str) -> TokenClaims:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM],
                             options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise TokenError("Token expired")
    except jwt.InvalidTokenError:
        raise TokenError("Invalid token")
    if payload.get("token_type") != token_type:
        raise TokenError("Invalid token type")
    return TokenClaims(user_id=int(payload["sub"]), scopes=list(payload.get("scopes") or []))
```

- The algorithm list is pinned on decode; `exp` and `sub` are required.
- Passwords: argon2 via `pwdlib`; `verify_password` returns `False` on an
  unknown hash format instead of raising.
- Changing `JWT_SECRET` logs everyone out.

### Auth endpoints — `modules/auth`

| Endpoint | Behaviour |
|---|---|
| `POST /api/v1/auth/login` | OAuth2 password **form** (`username` = email), so Swagger's *Authorize* works. Same 401 `invalid_credentials` for unknown email and wrong password. Disabled user → 403. Updates `last_login_at`. Returns `{access_token, refresh_token, token_type, expires_in, user, scopes}` |
| `POST /api/v1/auth/refresh` | `{refresh_token}` → new pair. Reloads the user: disabled/deleted users can't refresh; **role changes take effect here** (scopes re-derived from the role) |
| `GET /api/v1/auth/me` | current user + scopes |

### Request guards — `modules/auth/deps.py`

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def get_current_user(request: Request, token: str = Depends(oauth2_scheme),
                     db: Session = Depends(get_db)) -> User:
    try:
        claims = verify_access_token(token)
    except TokenError as exc:
        raise AppException(code="unauthorized", status_code=401, detail=str(exc))
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:          # disabling a user locks them out at once
        raise AppException(code="unauthorized", status_code=401, detail="User not found or disabled")
    request.state.scopes = set(claims.scopes)
    return user

def require_scope(*required: Scope):
    """Passes if the token has ANY of `required`. Admins pass every check."""
    def dependency(request: Request, user: User = Depends(get_current_user)) -> User:
        if user.role == Role.ADMIN.value:
            return user
        needed = {s.value for s in required}
        if not needed & getattr(request.state, "scopes", set()):
            raise AppException(code="forbidden", status_code=403,
                               detail=f"Missing scope. Need one of {sorted(needed)}")
        return user
    return dependency
```

The guard also returns the acting user, which the service uses for audit:
`actor: User = Depends(require_scope(Scope.PROJECT_WRITE))`.

### WebSocket auth

Browsers can't set headers on a WebSocket, so the access token goes in the
query string (`/api/v1/ws/...?token=...`, TLS in production). Accept, verify
(in a threadpool: the DB is sync), then close with app codes: `4401` invalid
or expired token (client refreshes and reconnects), `4403` missing scope.

---

## 7. Authorization (roles and scopes) — `app/core/scopes.py`

```python
class Scope(str, Enum):
    PROJECT_READ = "project:read"
    PROJECT_WRITE = "project:write"
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    AUDIT_READ = "audit:read"

class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"

_VIEWER = [Scope.PROJECT_READ]

ROLE_SCOPES: Dict[Role, List[Scope]] = {
    Role.VIEWER: _VIEWER,
    Role.OPERATOR: _VIEWER + [Scope.PROJECT_WRITE],
    Role.ADMIN: list(Scope),
}

def scopes_for(role: str) -> List[str]:
    return [s.value for s in ROLE_SCOPES.get(Role(role), [])]
```

- Scopes are `resource:action`. **Routes check scopes, never role names.**
- Roles are presets of scopes; the user row stores only `role`.
- The access token carries the scopes, so a check costs no query.
- Every route except login/refresh/health has a guard.

### Users module invariants

- Emails normalized (strip + lower-case) in the schema; lookups use `func.lower(User.email)`.
- At least one active admin must remain (on demote, disable, delete).
- You can't demote, disable or delete yourself.
- Password changes are audited as `"password": "changed"`, never the value.
- The first admin is seeded from `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`
  at start-up, only when the users table is empty.

---

## 8. Errors

Services raise `AppException` (`core/exceptions.py`, no FastAPI import). One
handler in `main.py` returns a uniform, i18n-friendly body:

```json
{"code": "project_code_taken", "i18n_key": "errors.project_code_taken", "params": {}, "message": "Project code 'P1' is already used"}
```

```python
class AppException(Exception):
    def __init__(self, *, code: str, status_code: int = 400, detail: str | None = None,
                 params: dict[str, Any] | None = None):
        super().__init__(detail or code)
        self.status_code = status_code
        self.detail = {"code": code, "i18n_key": f"errors.{code}",
                       "params": params or {}, "message": detail or code}
```

| Class | Status | `code` |
|---|---|---|
| `AppException(code=...)` | 400 (or given) | given |
| `NotFoundError("project")` | 404 | `project_not_found` |
| `ConflictError(code, msg)` | 409 | given |
| `UpstreamError("payments", msg)` | 502 | `payments_unavailable` |
| `IntegrityError` (global handler) | 409 | `conflict` |
| auth failures | 401 / 403 | `unauthorized` / `forbidden` |

The frontend switches on `code` and translates by `i18n_key`; `message` is a
developer fallback. Pydantic validation stays FastAPI's default 422.

---

## 9. API conventions

- Every router is prefixed `/api/v1/...` and tagged per module.
- Path ids are UUIDs: `/projects/{project_uuid}`.
- Status codes: `201` create, `204` delete, `200` otherwise.
- Children are created under the parent (`POST /projects/{uuid}/tasks`) and
  then addressed flat (`PATCH /tasks/{uuid}`).
- Lists: `Page[XResponse]` + `paginate(db, service.list_stmt(...))`; small fixed lists may return `List[...]`.
- JSON is snake_case everywhere.
- `GET /health` — no auth, no DB, for liveness probes.

### PATCH semantics — `PatchModel`

```python
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

class TaskUpdate(PatchModel):
    nullable = frozenset({"due_date"})
    name: Optional[Name] = None
    due_date: Optional[date] = None
```

---

## 10. Audit log — `modules/audit`

One `audit_log` table: `actor_user_id` (FK, `SET NULL`), `actor_email`,
`action` (create | update | delete), `entity`, `entity_uuid`, `before`, `after` (JSON).

```python
before = audit.snapshot(obj, FIELDS)
# ...apply changes...
audit.record(self.db, actor, "update", "project", obj.uuid, before=before, after=audit.snapshot(obj, FIELDS))
self.db.commit()
```

- `record()` only `db.add`s to the caller's session: **the change and its log
  line commit together or not at all.**
- Each service declares the fields it audits (`PROJECT_FIELDS = (...)`); secrets are never snapshotted.
- `actor=None` is logged as `"system"` (seed, background jobs).
- `GET /api/v1/audit?entity=&entity_uuid=` — newest first, paginated, `audit:read`.

---

## 11. Calling other services — `client.py`

Only for modules that talk to another HTTP service.

```python
class PaymentsClient:
    def __init__(self, base_url: str, api_key: str, timeout: float,
                 transport: httpx.BaseTransport | None = None):
        self.configured = bool(api_key)
        self._http = httpx.Client(base_url=base_url.rstrip("/"),
                                  headers={"Authorization": f"Bearer {api_key}"},
                                  timeout=timeout, transport=transport)

    def _call(self, method: str, path: str, **kwargs):
        if not self.configured:
            raise UpstreamError("payments", "PAYMENTS_API_KEY is not set")
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise UpstreamError("payments", f"unreachable ({exc.__class__.__name__})")
        if resp.status_code >= 400:
            raise UpstreamError("payments", f"HTTP {resp.status_code}: {resp.text}")
        return resp.json()

@lru_cache
def get_payments_client() -> PaymentsClient:
    return PaymentsClient(settings.PAYMENTS_URL, settings.PAYMENTS_API_KEY, settings.PAYMENTS_TIMEOUT_S)
```

- One long-lived `httpx.Client` per process (`@lru_cache` factory) for connection pooling.
- Injected with `Depends(get_payments_client)`; services take it in `__init__`.
  Tests swap it with `app.dependency_overrides`.
- Every failure becomes `UpstreamError` (502): the UI can tell "service down" from "no data".
- Service keys live only in backend env; the browser never sees them.
- Cached short-lived tokens from another service go in a dict behind a
  `threading.Lock`, renewed a margin before expiry.

---

## 12. Application start-up — `main.py`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    seed()                                         # idempotent
    worker = get_worker() if settings.WORKER_ENABLED else None
    if worker:
        worker.start()
    yield
    if worker:
        await worker.stop()

app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan,
              swagger_ui_parameters={"docExpansion": "none"})
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
for _router in ALL_ROUTERS:
    app.include_router(_router)
add_pagination(app)

@app.exception_handler(AppException)
async def app_exception_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(exc.detail))

@app.exception_handler(IntegrityError)
async def integrity_error_handler(request, exc):
    logger.warning("integrity error on %s %s: %s", request.method, request.url.path, exc.orig)
    return JSONResponse(status_code=409, content={"code": "conflict", "i18n_key": "errors.conflict",
                                                  "params": {}, "message": "The change conflicts with existing data"})

@app.get("/health")
def health_check():
    return {"status": "ok"}
```

Seeds check "already there?" before inserting, so restarts are safe. Default
rows whose values need a business decision can be seeded **disabled**.

---

## 13. Background work and WebSockets (when needed)

- One `asyncio` task per process, started/stopped in `lifespan`, behind an `<X>_ENABLED` setting.
- Blocking work (sync DB, httpx) runs in `asyncio.to_thread(...)`; never block the event loop.
- **The loop never dies:** each iteration is wrapped in try/except and logged;
  an upstream outage keeps the last state and is announced once, not every tick.
- WebSocket fan-out: a hub holding the client set under an `asyncio.Lock`,
  sending with `asyncio.gather`; a failed send drops the client. One reader
  feeds all sockets, so N screens cost one upstream read.
- Typed JSON messages (`{"type": "snapshot" | "update" | "status", ...}`):
  full snapshot on connect, then only what changed; app-level `ping`/`pong`.
- Single-process assumption: with several uvicorn workers each runs its own
  loop. To scale out, move the loop to its own worker and fan out via Redis/Kafka.

---

## 14. Testing — `tests/conftest.py`

1. **Set env before importing the app** (settings are read at import time):

   ```python
   os.environ.update({
       "JWT_SECRET": secrets.token_hex(32),
       "DATABASE_URL": "sqlite://",
       "SEED_ADMIN_EMAIL": "", "SEED_ADMIN_PASSWORD": "",
       "WORKER_ENABLED": "false",
   })
   from app.main import app  # noqa: E402
   ```
2. `db` fixture: SQLite in memory, `StaticPool`, `check_same_thread=False`, `Base.metadata.create_all(engine)`.
3. `client` fixture: `app.dependency_overrides[get_db] = lambda: db` (+ fake clients), cleared after the test.
4. Fakes for external clients with the same method names; they record calls for assertions.
5. Helpers: `make_user(db, email, role)`, `auth(client, email)` → `{"Authorization": "Bearer ..."}`,
   fixtures `admin`, `operator`, `viewer`, and a builder for a standard data set.

For every feature, test through HTTP (`TestClient`):
- happy path per endpoint;
- each role: allowed vs 403; 401 with no token, a bad token, a refresh token used as access;
- validation 422 (lengths, patterns, null in PATCH);
- 404 for unknown UUIDs, 409 for duplicates;
- external service down / not configured → 502;
- audit rows with correct before/after;
- invariants (last admin, self-demotion, cross-parent moves).

Use SQLite-compatible types (`Uuid`, `JSON`, `DateTime(timezone=True)`). If you
need Postgres-only features (JSONB operators, arrays), add a Postgres test job.

Run: `uv run pytest -q`.

---

## 15. Build and run

```bash
cp .env.example .env                                # fill in secrets
docker compose up -d db                             # Postgres
uv sync                                             # .venv from uv.lock (incl. dev group)
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8020    # http://localhost:8020/docs
docker compose --profile full up -d --build         # everything in Docker
```

`pyproject.toml`:

```toml
[project]
name = "my-service"
version = "0.0.0"            # releases are git tags; never bumped
requires-python = "~=3.12.0"
dependencies = [
  "fastapi", "fastapi-pagination", "uvicorn[standard]", "python-multipart",
  "sqlalchemy>=2", "alembic", "psycopg2-binary", "pydantic>=2", "pydantic-settings",
  "httpx", "pyjwt", "pwdlib[argon2]", "tzdata",
]

[dependency-groups]
dev = ["pytest"]
```

`Dockerfile` (multi-stage):

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/srv/.venv/bin:$PATH"
WORKDIR /srv
COPY --from=builder /srv/.venv /srv/.venv
COPY alembic.ini .
COPY app app
EXPOSE 8020
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8020"]
```

- `uv add <pkg>` / `uv add --dev <pkg>`; commit `pyproject.toml` and `uv.lock` together.
- Slim images have no timezone database: keep `tzdata` if you use `zoneinfo`.
- CI: tests + a vulnerability scan (e.g. Trivy, failing on HIGH/CRITICAL with a fix).

---

## 16. Checklist: adding a module

1. `app/modules/<name>/models.py` — inherit `BaseModel`; FKs with `ondelete`; named constraints.
2. Import the models in `app/models/__init__.py`.
3. `uv run alembic revision --autogenerate -m "<name>"` → review → `upgrade head`.
4. `schemas.py` — `XCreate`, `XUpdate(PatchModel)` (+ `nullable`), `XResponse(from_attributes=True)`.
5. New scopes in `Scope` and in the `ROLE_SCOPES` presets.
6. `service.py` — `XService(db)`: `x_or_404`, `list_stmt`, create/update/delete with uniqueness checks, audit, commit.
7. `router.py` — `APIRouter(prefix="/api/v1/...", tags=[...])`, `require_scope(...)` on every route, `response_model`, status codes.
8. Add the router to `ALL_ROUTERS` in `app/modules/__init__.py`.
9. New settings → `config.py` + `.env.example`.
10. `tests/test_<name>.py` (list in §14).
11. Update the README API table.

## 17. Checklist: new project from this blueprint

1. Copy `app/core/`, `app/main.py`, `app/models/__init__.py`, `app/modules/{auth,users,audit}`,
   `app/alembic/`, `alembic.ini`, `tests/conftest.py`, `Dockerfile`, `docker-compose.yml`,
   `pyproject.toml`, `.python-version`, `.env.example`, `.gitignore`.
2. Rename: `PROJECT_NAME`, compose project/DB name/user, host ports.
3. Define the domain's `Scope` values and `ROLE_SCOPES`.
4. Delete old migrations; generate a fresh initial migration.
5. Keep only the first-admin seed in `core/seed.py`.
6. `uv lock`, `uv run pytest -q`, `docker build .`.
