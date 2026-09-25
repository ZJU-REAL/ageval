"""Harbor-style jobs API tests for local suite-runs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ageval.config.errors import ConfigError
from ageval.viewer import jobs

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"


def _seed_suite_run(db: Path, job_id: str = "suite_demo_job_001") -> str:
    suite_dir = db / ".ageval" / "suite-runs" / job_id
    suite_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema": "ageval.suite.summary/1",
        "suite_run_id": job_id,
        "dataset_id": "test/suite-min",
        "dataset_version": "0.1.0",
        "agent_label": "codex",
        "model_label": "gpt-test",
        "provider_label": "openai",
        "job_overlay": {"environment": "docker", "agent_profiles": {}},
        "created_at": "2026-07-14T19:46:20Z",
        "tasks": [
            {"task_id": "alpha", "status": "PASS", "score": 1.0, "run_id": "run_a"},
            {"task_id": "beta", "status": "FAIL", "score": 0.0, "run_id": "run_b"},
            {"task_id": "gamma", "status": "PASS", "score": 1.0, "run_id": "run_c"},
        ],
        "task_refs": [
            {"task_id": "alpha", "status": "PASS", "score": 1.0, "run_id": "run_a"},
            {"task_id": "beta", "status": "FAIL", "score": 0.0, "run_id": "run_b"},
            {"task_id": "gamma", "status": "PASS", "score": 1.0, "run_id": "run_c"},
        ],
        "metrics": {
            "pass_rate": 2 / 3,
            "mean_score": 2 / 3,
            "n_tasks": 3,
            "n_pass": 2,
            "n_fail": 1,
            "n_error": 0,
            "missing_score_as": 0.0,
        },
        "exit_code": 1,
        "note": "per-task evaluator verdicts only; no suite-level PASS",
    }
    (suite_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return job_id


def _write_lock(evidence: Path, *, task_id: str) -> None:
    (evidence / "lock.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _clean_db(tmp_path: Path) -> Path:
    """Copy fixture without leftover .ageval suite-runs from local smokes."""
    db = tmp_path / "db"
    shutil.copytree(SUITE, db, ignore=shutil.ignore_patterns(".ageval"))
    return db


def test_get_job_from_attempts_only_summary(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = "suite_attempts_only"
    suite_dir = db / ".ageval" / "suite-runs" / job_id
    suite_dir.mkdir(parents=True, exist_ok=True)
    (suite_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema": "ageval.suite.summary/1",
                "suite_run_id": job_id,
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
                "attempts": [
                    {
                        "task_id": "alpha",
                        "attempt_index": 0,
                        "status": "PASS",
                        "score": 1.0,
                        "run_id": "run_a",
                    },
                    {
                        "task_id": "beta",
                        "attempt_index": 0,
                        "status": "FAIL",
                        "score": 0.0,
                        "run_id": "run_b",
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    detail = jobs.get_job(db, job_id)
    assert detail["task_count"] == 2
    ids = {row["task_id"] for row in detail["tasks"]}
    assert ids == {"alpha", "beta"}
    by_id = {row["task_id"]: row for row in detail["tasks"]}
    assert by_id["alpha"]["status"] == "PASS"
    assert by_id["beta"]["status"] == "FAIL"


def test_list_and_get_job(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)

    listed = jobs.list_jobs(db)
    assert listed["count"] == 1
    assert listed["items"][0]["job_id"] == job_id
    assert listed["items"][0]["mean_score"] == pytest.approx(2 / 3)
    assert listed["items"][0]["agent_label"] == "codex"
    assert listed["items"][0]["environment"] == "docker"
    assert listed["items"][0]["started"] == "2026-07-14T19:46:20Z"
    assert listed["items"][0]["dataset_ref"] == "test/suite-min@0.1.0"

    detail = jobs.get_job(db, job_id)
    assert detail["task_count"] == 3
    assert detail["tasks"][0]["task_id"] == "alpha"
    assert detail["tasks"][1]["status"] == "FAIL"
    assert detail["job"]["dataset_ref"] == "test/suite-min@0.1.0"
    assert detail["tasks"][0]["dataset"] == "test/suite-min@0.1.0"


def test_suite_identity_is_summary_not_opened_yaml(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    summary_path = db / ".ageval" / "suite-runs" / job_id / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["dataset_id"] = "official/tau3-airline"
    summary["dataset_version"] = "0.1.0"
    summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
    row = jobs.list_jobs(db)["items"][0]
    assert row["dataset_ref"] == "official/tau3-airline@0.1.0"
    assert row["dataset_id"] == "official/tau3-airline"
    detail = jobs.get_job(db, job_id)
    assert detail["job"]["dataset_ref"] == "official/tau3-airline@0.1.0"


def test_missing_suite_identity_fails_closed(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    summary_path = db / ".ageval" / "suite-runs" / job_id / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    del summary["dataset_version"]
    summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="missing dataset_id@version"):
        jobs.list_jobs(db)


def test_single_job_identity_is_lock_not_opened_yaml(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    evidence = _write_attempt_evidence(db, "run_locked", task_id="alpha", kind="docker")
    lock_path = evidence / "lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["dataset_id"] = "official/tau3-airline"
    lock["dataset_version"] = "0.1.0"
    lock_path.write_text(json.dumps(lock) + "\n", encoding="utf-8")
    row = next(item for item in jobs.list_jobs(db)["items"] if item["job_id"] == "run_locked")
    assert row["dataset_ref"] == "official/tau3-airline@0.1.0"
    detail = jobs.get_job(db, "run_locked")
    assert detail["job"]["dataset_ref"] == "official/tau3-airline@0.1.0"
    assert detail["tasks"][0]["dataset"] == "official/tau3-airline@0.1.0"


def test_missing_lock_identity_fails_closed(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    evidence = _write_attempt_evidence(db, "run_nolock", task_id="alpha", kind="docker")
    lock = json.loads((evidence / "lock.json").read_text(encoding="utf-8"))
    del lock["dataset_id"]
    (evidence / "lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="missing dataset_id@version"):
        jobs.list_jobs(db)


def test_suite_job_axes_come_from_attempt_lock_overlay(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    run_id = "run_e2b_dsh"
    evidence = _write_attempt_evidence(db, run_id, task_id="alpha", kind="e2b")
    (evidence / "lock.json").write_text(
        json.dumps(
            {
                "task_id": "alpha",
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
                "environment": "e2b",
                "job_overlay": {
                    "environment": "e2b",
                    "agent_profiles": {
                        "solver": {"executor": "dsh", "model": "glm-5.2"},
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    job_id = "suite_e2b_dsh"
    suite_dir = db / ".ageval" / "suite-runs" / job_id
    suite_dir.mkdir(parents=True, exist_ok=True)
    (suite_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema": "ageval.suite.summary/1",
                "suite_run_id": job_id,
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
                "agent_label": "e2b/dsh",
                "model_label": "glm-5.2",
                "tasks": [
                    {
                        "task_id": "alpha",
                        "status": "PASS",
                        "score": 1.0,
                        "run_id": run_id,
                    }
                ],
                "metrics": {
                    "n_tasks": 1,
                    "n_pass": 1,
                    "n_fail": 0,
                    "mean_score": 1.0,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    row = next(item for item in jobs.list_jobs(db)["items"] if item["job_id"] == job_id)
    assert row["environment"] == "e2b"
    assert row["agent_label"] == "dsh"


def test_job_task_detail_and_command(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    payload = jobs.get_job_task(db, job_id, "beta")
    assert payload["task"]["status"] == "FAIL"
    assert payload["trials"][0]["reward"] == 0.0
    assert "ageval run" in (payload.get("run_command") or "")
    assert "--task beta" in (payload.get("run_command") or "")
    crumbs = payload["breadcrumb"]
    assert crumbs[0]["label"] == "Jobs"
    assert crumbs[0]["href"] == "/"
    assert crumbs[1]["label"] == job_id
    assert crumbs[2]["label"] == "beta"
    assert crumbs[2]["href"] is None


def test_list_empty_without_suite_runs(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    listed = jobs.list_jobs(db)
    assert listed["count"] == 0
    assert listed["items"] == []


def test_list_includes_single_task_attempt(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    run_id = "run_single_alpha"
    evidence = db / ".ageval" / "runs" / run_id
    evidence.mkdir(parents=True)
    (evidence / "result.json").write_text(
        json.dumps(
            {
                "task_id": "alpha",
                "status": "PASS",
                "score": 1.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_lock(evidence, task_id="alpha")
    listed = jobs.list_jobs(db)
    assert listed["count"] == 1
    row = listed["items"][0]
    assert row["job_id"] == run_id
    assert row["source_kind"] == "single"
    assert row["dataset_ref"] == "test/suite-min@0.1.0"
    assert row["source"] == "alpha"
    assert row["environment"] is None
    assert row["started"] is None
    assert row["duration"] is None
    detail = jobs.get_job(db, run_id)
    assert detail["task_count"] == 1
    assert detail["tasks"][0]["task_id"] == "alpha"


def test_list_includes_task_local_single_attempt(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    run_id = "run_task_local_beta"
    evidence = db / "tasks" / "beta" / ".ageval" / "runs" / run_id
    evidence.mkdir(parents=True)
    (evidence / "result.json").write_text(
        json.dumps(
            {
                "task_id": "beta",
                "status": "FAIL",
                "score": 0.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_lock(evidence, task_id="beta")
    listed = jobs.list_jobs(db)
    row = next(item for item in listed["items"] if item["job_id"] == run_id)
    assert row["source_kind"] == "single"
    assert row["source"] == "beta"
    assert row["task_id"] == "beta"


def test_job_task_exposes_attempt_run_ids_for_k(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = "suite_k2"
    suite_dir = db / ".ageval" / "suite-runs" / job_id
    suite_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema": "ageval.suite.summary/1",
        "suite_run_id": job_id,
        "dataset_id": "test/suite-min",
        "dataset_version": "0.1.0",
        "n_attempts": 2,
        "tasks": [
            {
                "task_id": "alpha",
                "status": "PASS",
                "score": 1.0,
                "run_id": "run_alpha_0",
                "n": 2,
                "c": 1,
            }
        ],
        "attempts": [
            {
                "task_id": "alpha",
                "run_id": "run_alpha_0",
                "status": "PASS",
                "score": 1.0,
                "attempt_index": 0,
            },
            {
                "task_id": "alpha",
                "run_id": "run_alpha_1",
                "status": "FAIL",
                "score": 0.0,
                "attempt_index": 1,
            },
        ],
        "metrics": {"n_tasks": 1, "n_pass": 1, "n_fail": 0, "mean_score": 1.0},
    }
    (suite_dir / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")

    detail = jobs.get_job(db, job_id)
    row = detail["tasks"][0]
    assert row["attempt_run_ids"] == ["run_alpha_0", "run_alpha_1"]
    assert row["n"] == 2
    assert row.get("previous") == []

    payload = jobs.get_job_task(db, job_id, "alpha")
    assert [t["run_id"] for t in payload["trials"]] == ["run_alpha_0", "run_alpha_1"]
    extra = db / ".ageval" / "runs" / "run_alpha_other"
    extra.mkdir(parents=True)
    (extra / "result.json").write_text(
        json.dumps({"task_id": "alpha", "status": "PASS", "score": 1.0}) + "\n",
        encoding="utf-8",
    )
    _write_lock(extra, task_id="alpha")
    listed = jobs.list_jobs(db)
    kinds = {item["job_id"]: item.get("source_kind") for item in listed["items"]}
    assert kinds.get(job_id) == "suite"
    assert kinds.get("run_alpha_other") == "single"
    assert "run_alpha_0" not in kinds
    assert "run_alpha_1" not in kinds


def test_single_task_not_duplicated_when_in_suite(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    _seed_suite_run(db)
    evidence = db / ".ageval" / "runs" / "run_a"
    evidence.mkdir(parents=True)
    (evidence / "result.json").write_text(
        json.dumps({"task_id": "alpha", "status": "PASS", "score": 1.0}) + "\n",
        encoding="utf-8",
    )
    listed = jobs.list_jobs(db)
    kinds = {item["job_id"]: item.get("source_kind") for item in listed["items"]}
    assert kinds.get("suite_demo_job_001") == "suite"
    assert "run_a" not in kinds


def _write_attempt_evidence(
    db: Path,
    run_id: str,
    *,
    task_id: str,
    kind: str,
    status: str = "PASS",
    score: float = 1.0,
) -> Path:
    evidence = db / ".ageval" / "runs" / run_id
    evidence.mkdir(parents=True)
    (evidence / "lock.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
                "environment": kind,
                "job_overlay": {"environment": kind, "agent_profiles": {}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (evidence / "result.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "status": status,
                "score": score,
                "kind": kind,
                "agent_invocations": 1,
                "capabilities_used": [],
                "cleanup_warning": None,
                "error": None,
                "evidence_path": f".ageval/runs/{run_id}",
                "gold_materialized_at": "evaluate",
                "logs": f".ageval/runs/{run_id}",
                "metrics": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (evidence / "summary.json").write_text(
        json.dumps(
            {
                "schema": "ageval.evidence.summary/1",
                "attempt_id": run_id,
                "run_id": run_id,
                "phase_timing": {
                    "schema": "ageval.phase_timing/1",
                    "phases": [
                        {"id": "run", "label": "Agent Execution", "duration_ms": 4500.0},
                    ],
                    "total_ms": 4500.0,
                    "started_at": "2026-08-20T10:00:00Z",
                    "finished_at": "2026-08-20T10:00:04Z",
                },
                "facts": [],
                "result": {"kind": kind, "status": status, "score": score},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return evidence


def test_suite_task_duration_averages_attempt_evidence(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    _write_attempt_evidence(db, "run_a", task_id="alpha", kind="docker")
    _write_attempt_evidence(db, "run_b", task_id="beta", kind="docker")
    beta = db / ".ageval" / "runs" / "run_b" / "summary.json"
    raw = json.loads(beta.read_text(encoding="utf-8"))
    raw["phase_timing"]["total_ms"] = 13500.0
    raw["phase_timing"]["phases"][0]["duration_ms"] = 13500.0
    beta.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    detail = jobs.get_job(db, job_id)
    by_id = {row["task_id"]: row for row in detail["tasks"]}
    assert by_id["alpha"]["duration"] == "4.5s"
    assert by_id["beta"]["duration"] == "14s"
    assert by_id["gamma"]["duration"] is None


def test_single_job_environment_and_timing_from_current_evidence(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    _write_attempt_evidence(db, "run_e2b_alpha", task_id="alpha", kind="e2b")
    _write_attempt_evidence(db, "run_ssh_beta", task_id="beta", kind="ssh")

    listed = jobs.list_jobs(db)
    by_id = {item["job_id"]: item for item in listed["items"]}
    e2b = by_id["run_e2b_alpha"]
    assert e2b["environment"] == "e2b"
    assert e2b["started"] == "2026-08-20T10:00:00Z"
    assert e2b["duration"] == "4.5s"
    ssh = by_id["run_ssh_beta"]
    assert ssh["environment"] == "ssh"
    assert ssh["started"] == "2026-08-20T10:00:00Z"
    assert ssh["duration"] == "4.5s"

    detail = jobs.get_job(db, "run_e2b_alpha")
    assert detail["job"]["environment"] == "e2b"
    assert detail["job"]["started"] == "2026-08-20T10:00:00Z"
    assert detail["job"]["duration"] == "4.5s"
    assert detail["tasks"][0]["duration"] == "4.5s"

    task = jobs.get_job_task(db, "run_e2b_alpha", "alpha")
    assert task["trials"][0]["started"] == "2026-08-20T10:00:00Z"
    assert task["trials"][0]["duration"] == "4.5s"
