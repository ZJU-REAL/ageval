"""Public entrypoint acceptance: ageval lock success / failure / determinism."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MINIMAL = REPO / "examples" / "datasets" / "minimal-demo"
INVALID = REPO / "examples" / "datasets" / "minimal-demo"
TASK = "terminal-jsonl-agg"


def _run_ageval(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Prefer the installed console script when available; fall back to module.
    cmd = [sys.executable, "-m", "ageval.cli.main", *args]
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO),
        env=env,
    )


def test_success_smoke() -> None:
    result = _run_ageval("lock", str(MINIMAL), "--task", TASK)
    assert result.returncode == 0, result.stderr
    assert result.stderr == "" or "warning" in result.stderr.lower()
    data = json.loads(result.stdout)
    assert data["task_id"] == TASK
    assert data["format"] == "ageval.task/1"
    assert data["dataset_id"] == "official/minimal-demo"
    assert data["dataset_version"] == "0.1.3"
    assert data["digest"].startswith("sha256:")
    assert "resolved_references" in data
    assert "resolution" in data
    # #59 job overlay is exportable with lock summary (no secrets).
    assert "job_overlay" in data
    assert data["job_overlay"]["agent_profiles"]["solver"]["executor"] == "acp"
    # No host absolute package path leakage.
    assert str(MINIMAL.resolve()) not in result.stdout


def test_expected_failure_unknown_task() -> None:
    result = _run_ageval("lock", str(INVALID), "--task", "not-a-member")
    assert result.returncode == 2
    assert result.stdout.strip() == ""
    assert "unknown_task" in result.stderr
    # Lock path must not create lock-store artifacts (run evidence under .ageval is unrelated).
    assert not (INVALID / ".ageval" / "locks").exists()
    assert not (REPO / ".ageval" / "locks").exists()


def test_determinism() -> None:
    r1 = _run_ageval("lock", str(MINIMAL), "--task", TASK)
    r2 = _run_ageval("lock", str(MINIMAL), "--task", TASK)
    assert r1.returncode == 0 and r2.returncode == 0
    assert r1.stdout == r2.stdout
    d1 = json.loads(r1.stdout)["digest"]
    d2 = json.loads(r2.stdout)["digest"]
    assert d1 == d2


def test_override_changes_digest() -> None:
    base = _run_ageval("lock", str(MINIMAL), "--task", TASK)
    over = _run_ageval(
        "lock",
        str(MINIMAL),
        "--task",
        TASK,
        "--set",
        '/agent_profiles/solver/model/id="other-model"',
        "--set",
        '/agent_profiles/solver/model/reasoning/effort="high"',
    )
    assert base.returncode == 0 and over.returncode == 0
    b = json.loads(base.stdout)
    o = json.loads(over.stdout)
    assert b["digest"] != o["digest"]
    sources = [e.get("source") for e in o["resolution"]]
    assert "cli-override" in sources


def test_no_ageval_artifacts_on_success(tmp_path: Path) -> None:
    result = _run_ageval("lock", str(MINIMAL), "--task", TASK, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    # `ageval lock` is read-only: must not create a lock store under cwd or Dataset.
    assert not (tmp_path / ".ageval").exists()
    assert not (MINIMAL / ".ageval" / "locks").exists()


def test_missing_task_flag_fails() -> None:
    result = _run_ageval("lock", str(MINIMAL))
    assert result.returncode == 2
    assert "--task" in result.stderr
    assert result.stdout.strip() == ""


def test_unknown_task_cli_fails() -> None:
    result = _run_ageval("lock", str(MINIMAL), "--task", "does-not-exist")
    assert result.returncode == 2
    assert "unknown_task" in result.stderr


def test_tasks_list_journeys() -> None:
    result = _run_ageval("tasks", str(REPO / "examples" / "datasets" / "minimal-demo"))
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["dataset_id"] == "official/minimal-demo"
    assert data["count"] == 3
    assert "terminal-jsonl-agg" in data["tasks"]


def test_no_task_local_import_on_lock() -> None:
    """Locking must not import package harness/evaluator modules."""
    # Run in a subprocess and inspect that examples were not imported as modules.
    code = f"""
import json, sys
from pathlib import Path
from ageval.application.composition import build_lock_command
repo = Path({str(REPO)!r})
cmd = build_lock_command()
summary = cmd.run(
    dataset_root=repo / "examples" / "datasets" / "minimal-demo", task_id="terminal-jsonl-agg"
)
assert summary["task_id"] == "terminal-jsonl-agg"
assert not any("terminal-jsonl-agg" in m and m.endswith("run") for m in sys.modules)
print(json.dumps({{"ok": True, "digest": summary["digest"]}}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["ok"] is True
