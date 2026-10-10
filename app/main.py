import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi_pagination import add_pagination
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.exceptions import AppException
from app.modules import ALL_ROUTERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from app.core.seed import seed
        seed()
    except Exception:  # never block /health on a seed problem (e.g. DB not migrated yet)
        logger.exception("start-up seed failed")
    worker = None
    if settings.WORKER_ENABLED:
        from app.worker import Worker
        worker = Worker()
        worker.start()
    yield
    if worker:
        await worker.stop()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan, swagger_ui_parameters={"docExpansion": "none"})
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
for _router in ALL_ROUTERS:
    app.include_router(_router)
add_pagination(app)


@app.exception_handler(AppException)
async def app_exception_handler(request, exc: AppException):
    return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(exc.detail))


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request, exc: IntegrityError):
    logger.warning("integrity error on %s %s: %s", request.method, request.url.path, exc.orig)
    return JSONResponse(status_code=409, content={"code": "conflict", "i18n_key": "errors.conflict", "params": {},
                                                  "message": "The change conflicts with existing data"})


FIELD_LABELS = {
    "requested_amount_mln": "Amount (mln UZS)", "term_months": "Term (months)", "purpose": "Purpose",
    "email": "Email", "username": "Email", "password": "Password", "full_name": "Full name",
    "company_name": "Company name", "stir": "STIR (tax ID)", "industry": "Industry", "region": "Region",
    "file": "File", "question": "Question", "reasoning": "Reasoning", "outcome": "Outcome",
}


def _human_error(err: dict) -> dict:
    field = next((str(p) for p in reversed(err.get("loc", [])) if isinstance(p, str) and p not in ("body", "query")), "")
    label = FIELD_LABELS.get(field, field.replace("_", " ").capitalize() or "This field")
    ctx, typ, value = err.get("ctx") or {}, err.get("type", ""), err.get("input")
    if field == "requested_amount_mln" and typ in ("less_than_equal", "less_than"):
        msg = (f"The amount is entered in millions of UZS. For {value:,.0f} so'm enter {value / 1_000_000:g}.".replace(",", " ")
               if isinstance(value, (int, float)) and value >= 1_000_000 else
               f"Amount (mln UZS) must be at most {ctx.get('le', ctx.get('lt'))}.")
    elif typ in ("less_than_equal", "less_than"):
        msg = f"{label} must be at most {ctx.get('le', ctx.get('lt'))}."
    elif typ in ("greater_than_equal", "greater_than"):
        msg = f"{label} must be at least {ctx.get('ge', ctx.get('gt'))}."
    elif typ == "missing":
        msg = f"{label} is required."
    elif typ in ("string_too_short",):
        n = ctx.get("min_length")
        msg = f"{label} is required." if n == 1 else f"{label} must be at least {n} characters."
    elif typ in ("string_too_long",):
        msg = f"{label} must be at most {ctx.get('max_length')} characters."
    elif typ in ("int_parsing", "float_parsing", "int_from_float", "decimal_parsing"):
        msg = f"{label} must be a number."
    elif typ == "string_pattern_mismatch" and field == "stir":
        msg = "STIR must be 9 digits starting with 2–7, e.g. 302 447 118."
    elif field in ("email", "username") and typ in ("value_error", "string_pattern_mismatch"):
        msg = "Enter a valid email address, e.g. name@company.uz."
    else:
        msg = f"{label}: {str(err.get('msg', 'invalid value')).removeprefix('Value error, ')}."
    return {"field": field, "message": msg}


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc: RequestValidationError):
    fields = [_human_error(e) for e in exc.errors()]
    return JSONResponse(status_code=422, content={
        "code": "validation_error", "i18n_key": "errors.validation_error", "params": {"fields": fields},
        "message": " ".join(dict.fromkeys(f["message"] for f in fields)) or "Some fields are invalid.",
        "detail": jsonable_encoder(exc.errors())})


@app.get("/health")
def health_check():
    return {"status": "ok"}
