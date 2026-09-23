"""Viewer HTTP rows carry the error object and the reached limit."""

from __future__ import annotations

import json
from pathlib import Path

from ageval.application.local_jobs.listing import get_job, list_jobs
from ageval.viewer.trials.surface import _trial_meta_from_evidence

_ERROR = {"phase": "run", "title": "ValueError", "message": "seed.txt is not a file"}


def _lock(task_id: str) -> dict[str, object]:
    return {
        "task_id": task_id,
        "dataset_id": "test/script-error",
        "dataset_version": "0.1.0",
        "environment": "local",
    }


def test_trial_meta_passes_the_error_object_and_limit(tmp_path: Path) -> None:
    evidence = tmp_path / "run_err"
    evidence.mkdir()
    (evidence / "lock.json").write_text(json.dumps(_lock("alpha")), encoding="utf-8")
    (evidence / "result.json").write_text(
        json.dumps({"status": "ERROR", "score": None, "error": _ERROR, "limit": None}),
        encoding="utf-8",
    )
    (evidence / "summary.json").write_text("{}", encoding="utf-8")
    meta = _trial_meta_from_evidence(evidence, run_id="run_err", task_id="alpha")
    assert meta["error"] == _ERROR
    assert meta["limit"] is None

    limited = tmp_path / "run_limit"
    limited.mkdir()
    (limited / "lock.json").write_text(json.dumps(_lock("alpha")), encoding="utf-8")
    (limited / "result.json").write_text(
        json.dumps(
            {
                "status": "FAIL",
                "score": 0.3,
                "error": None,
                "limit": "wall_time_seconds",
            }
        ),
        encoding="utf-8",
    )
    (limited / "summary.json").write_text("{}", encoding="utf-8")
    meta = _trial_meta_from_evidence(limited, run_id="run_limit", task_id="alpha")
    assert meta["error"] is None
    assert meta["limit"] == "wall_time_seconds"


def test_trial_meta_keeps_a_string_error(tmp_path: Path) -> None:
    evidence = tmp_path / "run_old"
    evidence.mkdir()
    (evidence / "lock.json").write_text(json.dumps(_lock("alpha")), encoding="utf-8")
    (evidence / "result.json").write_text(
        json.dumps({"status": "ERROR", "score": None, "error": {"phase": "evaluate"}}),
        encoding="utf-8",
    )
    (evidence / "summary.json").write_text("{}", encoding="utf-8")
    meta = _trial_meta_from_evidence(
        evidence,
        run_id="run_old",
        task_id="alpha",
        suite_row={"error": "suite_cancelled"},
    )
    assert meta["error"] == "suite_cancelled"


def test_job_rows_carry_error_and_limit(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    suite = root / ".ageval" / "suite-runs" / "suite_err"
    suite.mkdir(parents=True)
    (suite / "summary.json").write_text(
        json.dumps(
            {
                "suite_run_id": "suite_err",
                "dataset_id": "test/script-error",
                "dataset_version": "0.1.0",
                "created_at": "2026-09-23T00:00:00Z",
                "tasks": [
                    {
                        "task_id": "alpha",
                        "status": "ERROR",
                        "score": None,
                        "run_id": "run_err",
                        "error": _ERROR,
                        "limit": None,
                    }
                ],
                "task_refs": [
                    {
                        "task_id": "alpha",
                        "status": "ERROR",
                        "score": None,
                        "run_id": "run_err",
                        "error": _ERROR,
                        "limit": None,
                    }
                ],
                "attempts": [
                    {
                        "task_id": "alpha",
                        "status": "ERROR",
                        "score": None,
                        "run_id": "run_err",
                        "attempt_index": 0,
                        "error": _ERROR,
                        "limit": None,
                    }
                ],
                "metrics": {"n_tasks": 1, "n_pass": 0, "n_fail": 0, "n_error": 1},
                "exit_code": 2,
            }
        ),
        encoding="utf-8",
    )
    detail = get_job(root, "suite_err")
    task = detail["tasks"][0]
    assert task["error"] == _ERROR
    assert task["limit"] is None
    assert task["attempts"][0]["error"] == _ERROR

    evidence = root / ".ageval" / "runs" / "run_limit"
    evidence.mkdir(parents=True)
    (evidence / "lock.json").write_text(json.dumps(_lock("beta")), encoding="utf-8")
    (evidence / "result.json").write_text(
        json.dumps(
            {
                "status": "FAIL",
                "score": 0.2,
                "error": None,
                "limit": "agent_invocations",
                "task_id": "beta",
            }
        ),
        encoding="utf-8",
    )
    (evidence / "summary.json").write_text("{}", encoding="utf-8")
    listed = list_jobs(root)
    single = next(item for item in listed["items"] if item["job_id"] == "run_limit")
    assert single["error"] is None
    assert single["limit"] == "agent_invocations"
    single_detail = get_job(root, "run_limit")
    assert single_detail["tasks"][0]["limit"] == "agent_invocations"
    assert single_detail["tasks"][0]["error"] is None
    assert single_detail["tasks"][0]["attempts"][0]["limit"] == "agent_invocations"
