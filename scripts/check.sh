#!/usr/bin/env bash
# Local equivalent of CI jobs python-core, python-plugins, and python-registry.
# Those jobs rewrite the same .venv, so this script runs them one after another
# and restores the suite extras on the way out.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

restore_suite_extras() {
  uv sync --frozen --extra nooa --extra dsh --extra miniswe
}
trap restore_suite_extras EXIT

uv sync --frozen
uv run ruff format --check src tests plugins services scripts
uv run ruff check src tests plugins services scripts
uv run pyright
uv run python scripts/check_builtin_plugins.py
uv run python scripts/check_builtin_agents.py
uv run python scripts/gen_param_tables.py --check
uv run python scripts/gen_evidence_ts.py --check

export AGEVAL_OFFLINE_AGENT=1
export AGEVAL_SKIP_DOCKER=1
export AGEVAL_SKIP_REAL_CODEX=1
export AGEVAL_SKIP_REAL_PI=1
export AGEVAL_SKIP_REAL_OPENCODE=1
export AGEVAL_SKIP_REAL_ACP=1

uv run pytest --ignore=tests/registry -q

uv sync --frozen --extra miniswe --extra nooa --extra dsh
AGEVAL_REQUIRE_PLUGIN_DEPS=1 uv run pytest tests/plugins -q

uv sync --frozen --extra registry
uv run pytest tests/registry -q
