"""Suite task and attempt rows carry the run-phase limit next to status and score."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.application.suite.suite_run import SuitePlan, _run_one, _task_row_from_rollup


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
        error_phase = None

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
