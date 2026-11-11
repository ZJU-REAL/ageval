"""ACP expected failures: one clear error, never a quiet fallback."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ageval.plugins.contrib.acp import build_acp_executor
from ageval.plugins.contrib.acp.registry import get_entry, readiness_for
from ageval.plugins.errors import ExtensionMaterializeError

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "examples" / "datasets" / "minimal-demo"


def _cli(
    *args: str,
    offline: bool = True,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "AGEVAL_OFFLINE_AGENT": "1" if offline else "0"}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env=env,
        timeout=180,
    )


def test_unknown_entry_fails_the_lock() -> None:
    proc = _cli(
        "lock",
        str(CORE),
        "--task",
        "terminal-jsonl-agg",
        "--set",
        '/agent_profiles/solver/options/entry="not-registered"',
    )
    assert proc.returncode != 0
    assert "not-registered" in proc.stderr


def _blocked_import_env(tmp_path: Path, module: str, source: str) -> dict[str, str]:
    """Prepend a stub module that makes an unwanted import fail loudly."""
    (tmp_path / f"{module}.py").write_text(source, encoding="utf-8")
    existing = os.environ.get("PYTHONPATH")
    pythonpath = str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    return {"PYTHONPATH": pythonpath}


@pytest.mark.parametrize(
    ("module", "source", "marker"),
    [
        ("acp", 'raise ImportError("acp sdk deliberately unavailable")\n', "acp sdk"),
        ("pydantic", 'raise SystemError("simulated pydantic-core mismatch")\n', "pydantic-core"),
    ],
)
def test_unknown_entry_lock_does_not_import_runtime_sdk(
    tmp_path: Path, module: str, source: str, marker: str
) -> None:
    """Lock only reads static entry data; a broken SDK dependency must not crash it."""
    proc = _cli(
        "lock",
        str(CORE),
        "--task",
        "terminal-jsonl-agg",
        "--set",
        '/agent_profiles/solver/options/entry="not-registered"',
        extra_env=_blocked_import_env(tmp_path, module, source),
    )
    assert proc.returncode != 0
    assert "not-registered" in proc.stderr
    assert marker not in proc.stderr


def test_profile_without_an_entry_cannot_bind_the_executor() -> None:
    with pytest.raises(ExtensionMaterializeError):
        build_acp_executor(options={}, host=None, placement=None)  # type: ignore[arg-type]


def test_missing_adapter_reports_adapter_missing() -> None:
    """Mode 1 with the engine present but no ACP adapter is not "ready"."""
    descriptor = get_entry("codex")
    assert descriptor is not None

    def which(name: str) -> str | None:
        return "/somewhere/codex" if name == "codex" else None

    assert readiness_for(descriptor, which=which)["readiness"] == "adapter-missing"


def test_offline_run_never_claims_pass() -> None:
    proc = _cli("run", str(CORE), "--task", "terminal-jsonl-agg")
    assert proc.returncode != 0
    last = (proc.stdout or "").strip().splitlines()
    if last and last[-1].startswith("{"):
        assert json.loads(last[-1]).get("status") != "PASS"
