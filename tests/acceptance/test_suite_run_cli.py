"""Public CLI suite run acceptance (Spec 22)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"


def _ageval(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["AGEVAL_OFFLINE_AGENT"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env=env,
        timeout=180,
    )


def test_suite_full_concurrent_cli() -> None:
    """Full suite without --task; concurrency flag accepted; FAIL continues."""
    r = _ageval("run", str(SUITE), "--max-concurrent-tasks", "2")
    assert r.stdout.strip().startswith("{"), (r.stdout, r.stderr)
    data = json.loads(r.stdout.strip().splitlines()[-1])
    assert data.get("schema") == "ageval.suite.summary/1"
    assert data.get("dataset_id") == "test/suite-min"
    assert "tasks" in data and len(data["tasks"]) >= 3
    assert data.get("counts", {}).get("pass", 0) >= 3
    assert data.get("counts", {}).get("fail", 0) >= 1
    assert data.get("exit_code") == 1
    assert r.returncode == 1
    assert int(data.get("inflight_peak") or 0) <= 2
    assert data.get("note")
    assert "no suite-level" in data["note"]
    assert Path(data["summary_path"]).is_file()
    assert "suite_pass" not in data
    # Suite summary stores run_id only (no result_ref / evidence_ref).
    for row in data["tasks"]:
        assert "result_ref" not in row
        assert "evidence_ref" not in row
    run_ids = [t.get("run_id") for t in data["tasks"] if t.get("run_id")]
    assert len(run_ids) >= 3


def test_single_task_still_works() -> None:
    r = _ageval("run", str(SUITE), "--task", "alpha", "--max-concurrent-tasks", "2")
    assert r.returncode == 0, (r.stdout, r.stderr)
    data = json.loads(r.stdout.strip().splitlines()[-1])
    assert data.get("status") == "PASS"
    assert data.get("schema") != "ageval.suite.summary/1"


def test_unknown_task_suite_cli() -> None:
    r = _ageval("run", str(SUITE), "--task", "missing-task")
    assert r.returncode == 2
    assert "unknown_task" in r.stderr


def test_suite_json_flag_writes_document() -> None:
    r = _ageval("run", str(SUITE), "--json")
    assert r.stdout.strip().startswith("{"), (r.stdout, r.stderr)
    data = json.loads(r.stdout.strip().splitlines()[-1])
    assert data.get("schema") == "ageval.suite.summary/1"


def test_suite_tty_recap_skips_json_blob(monkeypatch) -> None:
    from typer.testing import CliRunner

    from ageval.cli.main import app

    monkeypatch.setattr("ageval.cli.cmd_campaign_run.use_json_stdout", lambda **_k: False)
    monkeypatch.setattr("ageval.cli.cmd_campaign_run.use_progress_bar", lambda **_k: False)
    result = CliRunner().invoke(app, ["run", str(SUITE)])
    assert result.exit_code == 1, result.stdout + (result.stderr or "")
    assert "actors_summary" not in result.stdout
    assert not result.stdout.lstrip().startswith("{")
    assert not result.stdout.lstrip().startswith("suite ")
    lines = [ln for ln in result.stdout.lstrip().splitlines() if ln]
    assert lines and set(lines[0]) <= {"─"}
    assert any("PASS" in ln for ln in lines)
    assert "summary  " in result.stdout
    assert "ageval view " in result.stdout
    assert "ageval results upload-suite " in result.stdout
    assert "FAIL" in result.stdout


def test_single_task_tty_recap(monkeypatch) -> None:
    from typer.testing import CliRunner

    from ageval.cli.main import app

    monkeypatch.setattr("ageval.cli.cmd_campaign_run.use_json_stdout", lambda **_k: False)
    monkeypatch.setattr("ageval.cli.cmd_campaign_run.use_progress_bar", lambda **_k: False)
    result = CliRunner().invoke(app, ["run", str(SUITE), "--task", "alpha"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert result.stdout.lstrip().startswith("task alpha")
    assert "PASS" in result.stdout
    assert "ageval view " in result.stdout
    assert "actors_summary" not in result.stdout


def test_retry_errors_requires_resume() -> None:
    r = _ageval("run", str(SUITE), "--task", "alpha", "--retry-errors")
    assert r.returncode == 2
    assert "suite_retry_errors_requires_resume" in r.stderr

    help_run = _ageval("run", "--help")
    assert help_run.returncode == 0
    assert "--retry-errors" in help_run.stdout


def test_replace_slot_requires_resume_and_task() -> None:
    r = _ageval("run", str(SUITE), "--task", "alpha", "--replace-slot")
    assert r.returncode == 2
    assert "suite_replace_requires_resume" in r.stderr

    r2 = _ageval("run", str(SUITE), "--resume-suite", "deadbeef", "--replace-slot")
    assert r2.returncode == 2
    assert "suite_replace_requires_task" in r2.stderr
