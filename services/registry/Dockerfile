# syntax=docker/dockerfile:1
# Public-mode Registry. Build context is the repository root.
# Do not default to --local / SQLite.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock VERSION README.md ./
COPY src ./src
COPY sdk/python ./sdk/python
COPY services/registry ./services/registry

RUN uv sync --frozen --extra registry --no-dev

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    AGEVAL_REGISTRY_HOST=0.0.0.0 \
    AGEVAL_REGISTRY_PORT=8700

EXPOSE 8700
CMD [".venv/bin/python", "-m", "services.registry.app", "--host", "0.0.0.0", "--port", "8700"]
