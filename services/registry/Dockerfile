# syntax=docker/dockerfile:1
# Public-mode Registry. Build context is the repository root.
# Do not default to --local / SQLite.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock VERSION README.md ./
COPY src ./src
COPY services/registry ./services/registry

# Cache mount keeps uv's download cache across builds; requires BuildKit
# (DOCKER_BUILDKIT=1 — the legacy builder rejects RUN --mount).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra registry --extra e2b --extra daytona --no-dev

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    AGEVAL_REGISTRY_HOST=0.0.0.0 \
    AGEVAL_REGISTRY_PORT=8700

EXPOSE 8700
CMD [".venv/bin/python", "-m", "services.registry.app", "--host", "0.0.0.0", "--port", "8700"]
