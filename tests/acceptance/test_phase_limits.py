"""Per-phase budgets through real ``ageval run`` on environment: local."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "phase-limits"
MINIMAL = REPO / "examples" / "datasets" / "minimal-demo"
TAU3 = REPO / "examples" / "datasets" / "tau3-airline-5"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    # The quota case must reach the parent. Offline short-circuits invoke in the SDK.
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    env["SOLVER_API_KEY"] = "ci-solver-locator"
    env["SOLVER_BASE_URL"] = "http://127.0.0.1:9/v1"
    env.setdefault("ZHIPU_API_KEY", "ci-offline-placeholder")
    env.setdefault("glm_coding_api_key", "ci-offline-placeholder")
    return env


def _ageval(dataset: Path, *args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(dataset),
        env=_env(),
        timeout=timeout,
    )


def _copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "phase-limits"))


def _document(proc: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert proc.stdout.strip(), proc.stderr
    parsed = json.loads(proc.stdout)
    assert isinstance(parsed, dict)
    return parsed


def _facts(dataset: Path, document: dict[str, object]) -> list[dict[str, object]]:
    logs = str(document.get("logs") or "")
    summary_path = dataset / logs / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    facts = summary.get("facts")
    assert isinstance(facts, list)
    return [fact for fact in facts if isinstance(fact, dict)]


def _error(document: dict[str, object]) -> dict[str, object]:
    error = document["error"]
    assert isinstance(error, dict)
    return error


def _phase_failed(facts: list[dict[str, object]], token: str) -> bool:
    for fact in facts:
        if fact.get("name") != "phase_failed":
            continue
        detail = fact.get("detail")
        if isinstance(detail, dict) and detail.get("title") == token:
            return True
    return False


def test_wall_clock_is_scored_and_recorded(tmp_path: Path) -> None:
    dataset = _copy(tmp_path)
    proc = _ageval(dataset, "run", str(dataset), "--task", "wall-hit", timeout=45)
    document = _document(proc)
    assert proc.returncode == 1, proc.stderr
    assert document["status"] == "FAIL"
    assert document["score"] == 0.3
    assert document["limit"] == "wall_time_seconds"
    assert document["error"] is None
    facts = _facts(dataset, document)
    assert any(
        fact.get("name") == "limit_reached"
        and isinstance(detail := fact.get("detail"), dict)
        and detail.get("name") == "wall_time_seconds"
        for fact in facts
    )
    assert any(fact.get("phase") == "evaluate" for fact in facts)


def test_environment_time_does_not_shrink_the_run_clock(tmp_path: Path) -> None:
    dataset = _copy(tmp_path)
    proc = _ageval(dataset, "run", str(dataset), "--task", "env-fits", timeout=45)
    document = _document(proc)
    assert proc.returncode == 0, proc.stderr
    assert document["status"] == "PASS"
    assert document["score"] == 1.0
    assert document["limit"] is None
    assert document["error"] is None
    facts = _facts(dataset, document)
    assert not any(fact.get("name") == "limit_reached" for fact in facts)


def test_environment_clock_is_error_and_run_does_not_start(tmp_path: Path) -> None:
    dataset = _copy(tmp_path)
    proc = _ageval(dataset, "run", str(dataset), "--task", "env-timeout", timeout=45)
    document = _document(proc)
    assert proc.returncode == 2, proc.stderr
    assert document["status"] == "ERROR"
    assert document["limit"] is None
    assert _error(document)["phase"] == "environment"
    assert _error(document)["title"] == "environment_timeout"
    facts = _facts(dataset, document)
    assert _phase_failed(facts, "environment_timeout")
    assert not any(fact.get("phase") == "run" for fact in facts)


def test_evaluate_clock_is_error(tmp_path: Path) -> None:
    dataset = _copy(tmp_path)
    proc = _ageval(dataset, "run", str(dataset), "--task", "eval-timeout", timeout=45)
    document = _document(proc)
    assert proc.returncode == 2, proc.stderr
    assert document["status"] == "ERROR"
    assert document["limit"] is None
    assert _error(document)["phase"] == "evaluate"
    assert _error(document)["title"] == "evaluate_timeout"
    assert _phase_failed(_facts(dataset, document), "evaluate_timeout")


def test_timeout_expired_from_run_is_error_without_a_limit(tmp_path: Path) -> None:
    dataset = _copy(tmp_path)
    proc = _ageval(dataset, "run", str(dataset), "--task", "run-timeout-exc", timeout=45)
    document = _document(proc)
    assert proc.returncode == 2, proc.stderr
    assert document["status"] == "ERROR"
    assert document["limit"] is None
    assert _error(document)["phase"] == "run"
    assert _error(document)["title"] == "TimeoutExpired"


def test_evaluator_error_status_fails_the_evaluate_phase(tmp_path: Path) -> None:
    dataset = _copy(tmp_path)
    proc = _ageval(dataset, "run", str(dataset), "--task", "eval-bad-status", timeout=45)
    document = _document(proc)
    assert proc.returncode == 2, proc.stderr
    assert document["status"] == "ERROR"
    assert document["limit"] is None
    assert _error(document)["phase"] == "evaluate"
    assert _error(document)["title"] == "evaluator_invalid_status"
    assert _phase_failed(_facts(dataset, document), "evaluator_invalid_status")


def test_invocation_limit_is_scored_after_run_raises(tmp_path: Path) -> None:
    dataset = _copy(tmp_path)
    proc = _ageval(dataset, "run", str(dataset), "--task", "invoke-limit", timeout=45)
    document = _document(proc)
    assert proc.returncode == 1, proc.stderr
    assert document["status"] == "FAIL"
    assert document["score"] == 0.2
    assert document["limit"] == "agent_invocations"
    assert document["error"] is None


def test_shipped_datasets_lock_with_their_current_limits() -> None:
    minimal = _ageval(MINIMAL, "lock", str(MINIMAL), "--task", "terminal-jsonl-agg")
    assert minimal.returncode == 0, minimal.stderr or minimal.stdout
    tau3 = _ageval(TAU3, "lock", str(TAU3), "--task", "airline-00")
    assert tau3.returncode == 0, tau3.stderr or tau3.stdout


def _run_shipped(dataset: Path, task: str, *, timeout: float) -> dict[str, object]:
    env = _env()
    env["AGEVAL_OFFLINE_AGENT"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", "run", str(dataset), "--task", task],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(dataset),
        env=env,
        timeout=timeout,
    )
    blob = proc.stderr + proc.stdout
    assert "unknown limits keys" not in blob, blob
    document = _document(proc)
    assert "limit" in document
    assert document["status"] in {"PASS", "FAIL", "ERROR"}
    return document


def test_tau3_runs_with_its_current_limits(tmp_path: Path) -> None:
    dataset = Path(
        shutil.copytree(TAU3, tmp_path / "tau3", ignore=shutil.ignore_patterns(".ageval"))
    )
    _run_shipped(dataset, "airline-00", timeout=120)
