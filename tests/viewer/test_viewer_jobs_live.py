"""Viewer Jobs on a live suite snapshot: one row, settled/planned trials (#193)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ageval.viewer import jobs

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"


def _seed_live_suite(db: Path, job_id: str = "suite_live_001") -> None:
    """Settled alpha(PASS) + beta(ERROR); gamma/delta-fail still planned."""
    suite_dir = db / ".ageval" / "suite-runs" / job_id
    suite_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema": "ageval.suite.summary/1",
        "suite_run_id": job_id,
        "dataset_id": "test/suite-min",
        "dataset_version": "0.1.0",
        "created_at": "2026-08-30T10:00:00Z",
        "task_ids": ["alpha", "beta"],
        "attempts": [
            {
                "task_id": "alpha",
                "attempt_index": 0,
                "status": "PASS",
                "score": 1.0,
                "run_id": "run_live_a",
                "phase": "terminal",
            },
            {
                "task_id": "beta",
                "attempt_index": 0,
                "status": "ERROR",
                "score": None,
                "run_id": "run_live_b",
                "phase": "terminal",
            },
        ],
        "tasks": [
            {"task_id": "alpha", "status": "PASS", "score": 1.0, "run_id": "run_live_a"},
            {"task_id": "beta", "status": "ERROR", "score": None, "run_id": "run_live_b"},
        ],
        "task_refs": [
            {"task_id": "alpha", "status": "PASS", "score": 1.0, "run_id": "run_live_a"},
            {"task_id": "beta", "status": "ERROR", "score": None, "run_id": "run_live_b"},
        ],
        "metrics": {
            "pass_rate": 0.5,
            "mean_score": 0.5,
            "n_tasks": 2,
            "n_pass": 1,
            "n_fail": 0,
            "n_error": 1,
            "missing_score_as": 0.0,
        },
        "exit_code": 2,
        "status": "running",
        "note": "suite in progress; observational snapshot of settled tasks",
    }
    (suite_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    progress = {
        "schema": "ageval.suite.progress/1",
        "suite_run_id": job_id,
        "dataset_id": "test/suite-min",
        "dataset_version": "0.1.0",
        "status": "running",
        "done": 2,
        "total": 4,
        "n_attempts": 1,
        "task_ids": ["alpha", "beta", "gamma", "delta-fail"],
        "running": [{"task_id": "gamma", "attempt_index": 0, "phase": "running"}],
        "updated_at": "2026-08-30T10:05:00Z",
        "cancel_requested": False,
    }
    (suite_dir / "progress.json").write_text(
        json.dumps(progress, indent=2) + "\n", encoding="utf-8"
    )


def _clean_db(tmp_path: Path) -> Path:
    db = tmp_path / "db"
    shutil.copytree(SUITE, db, ignore=shutil.ignore_patterns(".ageval"))
    return db


def test_list_jobs_shows_one_running_suite_row(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    _seed_live_suite(db)

    payload = jobs.list_jobs(db)
    suite_rows = [i for i in payload["items"] if i["source_kind"] == "suite"]
    assert len(suite_rows) == 1
    row = suite_rows[0]
    assert row["job_id"] == "suite_live_001"
    assert row["status"] == "running"
    assert row["pass_rate"] == 0.5
    assert row["trials_done"] == 2
    assert row["trials_total"] == 4
    assert row["progress"]["total"] == 4

    # Settled run ids are claimed by the suite row — no single-task job rows.
    single_ids = {i["job_id"] for i in payload["items"] if i["source_kind"] == "single"}
    assert "run_live_a" not in single_ids
    assert "run_live_b" not in single_ids
    assert payload["count"] == 1


def test_list_jobs_unclaimed_attempt_still_listed_alongside(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    _seed_live_suite(db)
    other = db / ".ageval" / "runs" / "run_outside"
    other.mkdir(parents=True)
    (other / "lock.json").write_text(
        json.dumps({"task_id": "gamma", "dataset_id": "test/suite-min", "dataset_version": "0.1.0"})
        + "\n",
        encoding="utf-8",
    )
    (other / "result.json").write_text(
        json.dumps(
            {
                "task_id": "gamma",
                "status": "FAIL",
                "score": 0.0,
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = jobs.list_jobs(db)
    single_ids = {i["job_id"] for i in payload["items"] if i["source_kind"] == "single"}
    assert single_ids == {"run_outside"}


def test_get_job_live_snapshot_lists_settled_tasks(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    _seed_live_suite(db)

    payload = jobs.get_job(db, "suite_live_001")
    assert payload["job"]["status"] == "running"
    assert payload["job"]["trials_done"] == 2
    assert payload["job"]["trials_total"] == 4
    assert [t["task_id"] for t in payload["tasks"]] == [
        "alpha",
        "beta",
        "gamma",
        "delta-fail",
    ]
    assert payload["progress"]["status"] == "running"


def test_get_job_live_marks_unsettled_planned_tasks_as_placeholders(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    _seed_live_suite(db)

    payload = jobs.get_job(db, "suite_live_001")
    by_id = {t["task_id"]: t for t in payload["tasks"]}
    # gamma is in flight; delta-fail has not started.
    assert by_id["gamma"]["status"] == "RUNNING"
    assert by_id["delta-fail"]["status"] == "PENDING"
    for tid in ("gamma", "delta-fail"):
        placeholder = by_id[tid]
        assert placeholder["run_id"] is None
        assert placeholder["score"] is None
        assert placeholder["attempts"] == []
    # Placeholders carry no metrics: settled aggregates stay untouched.
    assert payload["job"]["trials_done"] == 2
    assert payload["job"]["trials_total"] == 4


def test_get_job_before_first_summary_lists_planned_pending(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = "suite_planned_001"
    suite_dir = db / ".ageval" / "suite-runs" / job_id
    suite_dir.mkdir(parents=True)
    progress = {
        "schema": "ageval.suite.progress/1",
        "suite_run_id": job_id,
        "dataset_id": "test/suite-min",
        "dataset_version": "0.1.0",
        "status": "running",
        "done": 0,
        "total": 2,
        "n_attempts": 1,
        "task_ids": ["alpha", "beta"],
        "running": [{"task_id": "alpha", "attempt_index": 0, "phase": "running"}],
        "updated_at": "2026-08-30T10:05:00Z",
        "cancel_requested": False,
    }
    (suite_dir / "progress.json").write_text(
        json.dumps(progress, indent=2) + "\n", encoding="utf-8"
    )

    payload = jobs.get_job(db, job_id)
    by_id = {t["task_id"]: t for t in payload["tasks"]}
    assert by_id["alpha"]["status"] == "RUNNING"
    assert by_id["beta"]["status"] == "PENDING"
    assert payload["task_count"] == 2


def test_final_suite_row_keeps_finished_shape(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = "suite_done_001"
    suite_dir = db / ".ageval" / "suite-runs" / job_id
    suite_dir.mkdir(parents=True)
    summary = {
        "schema": "ageval.suite.summary/1",
        "suite_run_id": job_id,
        "dataset_id": "test/suite-min",
        "dataset_version": "0.1.0",
        "created_at": "2026-08-30T09:00:00Z",
        "task_ids": ["alpha"],
        "attempts": [
            {"task_id": "alpha", "attempt_index": 0, "status": "PASS", "run_id": "run_done_a"}
        ],
        "tasks": [{"task_id": "alpha", "status": "PASS", "score": 1.0, "run_id": "run_done_a"}],
        "task_refs": [{"task_id": "alpha", "status": "PASS", "score": 1.0, "run_id": "run_done_a"}],
        "metrics": {
            "pass_rate": 1.0,
            "mean_score": 1.0,
            "n_tasks": 1,
            "n_pass": 1,
            "n_fail": 0,
            "n_error": 0,
            "missing_score_as": 0.0,
        },
        "exit_code": 0,
        "status": "complete",
        "note": "per-task evaluator verdicts only; no suite-level PASS",
    }
    (suite_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    payload = jobs.list_jobs(db)
    row = next(i for i in payload["items"] if i["source_kind"] == "suite")
    assert row["status"] == "complete"
    assert row["trials_done"] == 1
    assert row["trials_total"] == 1
    assert "progress" not in row
    assert row["task_refs"] == [
        {
            "task_id": "alpha",
            "status": "PASS",
            "score": 1.0,
            "run_id": "run_done_a",
            "n": 1,
            "c": 1,
            "attempt_run_ids": ["run_done_a"],
            "has_attempt_content": True,
        }
    ]


def test_list_jobs_reads_stored_usage_without_scanning_runs(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = "suite_priced"
    run_id = "run_priced"
    suite_dir = db / ".ageval" / "suite-runs" / job_id
    suite_dir.mkdir(parents=True)
    run_dir = db / ".ageval" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "trajectory.jsonl").write_text(
        json.dumps(
            {
                "type": "terminal",
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    summary = {
        "schema": "ageval.suite.summary/1",
        "suite_run_id": job_id,
        "dataset_id": "test/suite-min",
        "dataset_version": "0.1.0",
        "created_at": "2026-08-30T09:00:00Z",
        "task_ids": ["alpha"],
        "attempts": [{"task_id": "alpha", "attempt_index": 0, "status": "PASS", "run_id": run_id}],
        "tasks": [{"task_id": "alpha", "status": "PASS", "score": 1.0, "run_id": run_id}],
        "task_refs": [{"task_id": "alpha", "status": "PASS", "score": 1.0, "run_id": run_id}],
        "job_overlay": {
            "agent_profiles": {"solver": {"model": "deepseek/deepseek-v4-pro"}},
        },
        "metrics": {
            "pass_rate": 1.0,
            "mean_score": 1.0,
            "n_tasks": 1,
            "n_pass": 1,
            "n_fail": 0,
            "n_error": 0,
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 3,
                "cost_source": "estimated",
                "cost_usd_estimated": 0.02,
            },
        },
        "exit_code": 0,
        "status": "complete",
    }
    (suite_dir / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")

    payload = jobs.list_jobs(db)
    row = next(i for i in payload["items"] if i["job_id"] == job_id)
    assert row["metrics"]["usage"] == summary["metrics"]["usage"]
