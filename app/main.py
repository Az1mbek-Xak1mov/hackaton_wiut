import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
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


@app.get("/health")
def health_check():
    return {"status": "ok"}
