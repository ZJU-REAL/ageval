"""Suite task and attempt rows carry the run-phase limit next to status and score."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.application.suite.suite_metrics import task_refs_for_summary
from ageval.application.suite.suite_run import SuitePlan, _run_one, _task_row_from_rollup
from ageval.config.errors import ConfigError


def test_task_row_keeps_the_primary_attempt_limit() -> None:
    row = _task_row_from_rollup(
        {
            "task_id": "t",
            "status": "FAIL",
            "score": 0.3,
            "n": 1,
            "c": 0,
            "run_id": "r",
            "attempts": [
                {
                    "status": "FAIL",
                    "score": 0.3,
                    "limit": "wall_time_seconds",
                    "metrics": {},
                    "attempt_index": 0,
                    "exit_code": 1,
                }
            ],
        }
    )
    assert row["status"] == "FAIL"
    assert row["score"] == 0.3
    assert row["limit"] == "wall_time_seconds"


@pytest.mark.asyncio
async def test_attempt_row_carries_limit(tmp_path: Path) -> None:
    class _Result:
        status = "FAIL"
        score = 0.3
        limit = "agent_invocations"
        metrics = {"n": 1}
        evidence_path = None
        logs = None

    async def run_fn(*_args: object, **_kwargs: object) -> tuple[int, _Result]:
        return 1, _Result()

    plan = SuitePlan(
        dataset_id="test/phase-limits",
        dataset_version="0.1.0",
        dataset_root=tmp_path,
        task_ids=["t"],
        max_concurrent_tasks=1,
    )
    row = await _run_one(plan, "t", 0, overrides=None, run_fn=run_fn)
    assert row["status"] == "FAIL"
    assert row["score"] == 0.3
    assert row["limit"] == "agent_invocations"


@pytest.mark.asyncio
async def test_error_attempt_row_copies_the_error_object(tmp_path: Path) -> None:
    error = {"phase": "run", "title": "ValueError", "message": "seed.txt is not a file"}

    class _Result:
        status = "ERROR"
        score = None
        limit = None
        metrics: dict[str, object] = {}
        evidence_path = None
        logs = None

        def __init__(self) -> None:
            self.error = error

    async def run_fn(*_args: object, **_kwargs: object) -> tuple[int, _Result]:
        return 2, _Result()

    plan = SuitePlan(
        dataset_id="test/script-error",
        dataset_version="0.1.0",
        dataset_root=tmp_path,
        task_ids=["t"],
        max_concurrent_tasks=1,
    )
    row = await _run_one(plan, "t", 0, overrides=None, run_fn=run_fn)
    assert row["status"] == "ERROR"
    assert row["score"] is None
    assert row["limit"] is None
    assert row["error"] == error


@pytest.mark.asyncio
async def test_config_error_before_a_phase_has_null_phase(tmp_path: Path) -> None:
    async def run_fn(*_args: object, **_kwargs: object) -> tuple[int, object]:
        raise ConfigError("invalid_package", "broken", location="ageval.yaml")

    plan = SuitePlan(
        dataset_id="test/script-error",
        dataset_version="0.1.0",
        dataset_root=tmp_path,
        task_ids=["t"],
        max_concurrent_tasks=1,
    )
    row = await _run_one(plan, "t", 0, overrides=None, run_fn=run_fn)
    assert row["status"] == "ERROR"
    assert row["error"]["phase"] is None
    assert row["error"]["title"] == "ConfigError"
    assert "invalid_package" in row["error"]["message"]


def test_task_refs_follow_the_run_id_attempt() -> None:
    refs = task_refs_for_summary(
        [
            {
                "task_id": "a",
                "status": "FAIL",
                "score": 0.2,
                "run_id": "r2",
            }
        ],
        attempts=[
            {
                "task_id": "a",
                "run_id": "r1",
                "status": "ERROR",
                "attempt_index": 0,
                "error": {"phase": "run", "title": "ValueError", "message": "seed"},
                "limit": None,
            },
            {
                "task_id": "a",
                "run_id": "r2",
                "status": "FAIL",
                "attempt_index": 1,
                "error": None,
                "limit": "wall_time_seconds",
            },
        ],
    )
    assert refs[0]["run_id"] == "r2"
    assert refs[0]["error"] is None
    assert refs[0]["limit"] == "wall_time_seconds"
