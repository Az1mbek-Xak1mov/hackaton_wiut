FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 UV_HTTP_TIMEOUT=300
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-default-groups

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/srv/.venv/bin:$PATH" \
    FILES_DIR=/data/files EVAL_RESULTS_DIR=/srv/eval/results
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-uzb tesseract-ocr-uzb-cyrl \
      tesseract-ocr-rus tesseract-ocr-eng libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY --from=builder /srv/.venv /srv/.venv
COPY alembic.ini .
COPY app app
COPY data/seed /srv/data/seed
RUN mkdir -p /data/files
# build metadata (and OMP_THREAD_LIMIT=1: one OCR thread per worker process) last, so a new commit
# does not invalidate the apt/uv layers
ARG GIT_SHA=dev
ARG BUILT_AT=""
ENV GIT_SHA=${GIT_SHA} BUILT_AT=${BUILT_AT} OMP_THREAD_LIMIT=1
EXPOSE 8020
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8020 --workers 2"]
