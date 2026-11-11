"""Task budgets apply after slot recovery/retry selection, before dispatch."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.application.suite.suite_run import (
    execute_suite_run,
    plan_suite_run,
    request_suite_cancel,
)
from ageval.config.errors import ConfigError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/datasets/suite-min"


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    return Path(
        shutil.copytree(FIXTURE, tmp_path / "dataset", ignore=shutil.ignore_patterns(".ageval"))
    )


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2"])
def test_invalid_task_budget(dataset: Path, value) -> None:  # noqa: ANN001
    with pytest.raises(ConfigError) as caught:
        plan_suite_run(dataset, max_tasks=value)
    assert caught.value.location == "--max-tasks"


@pytest.mark.asyncio
async def test_budget_resume_and_always_k(dataset: Path) -> None:
    calls: list[tuple[str, int]] = []

    async def runner(root, task_id, *, attempt_index=0, **kwargs):  # noqa: ANN001
        calls.append((task_id, attempt_index))
        await asyncio.sleep(0.01)
        return 0, SimpleNamespace(status="PASS", score=1.0, evidence_path=None, logs=None)

    plan = plan_suite_run(dataset, max_tasks=2, n_attempts=2, max_concurrent_tasks=3)
    ids = list(plan.task_ids)
    first = await execute_suite_run(plan, run_fn=runner)
    assert set(calls) == {(tid, i) for tid in ids[:2] for i in range(2)}
    assert first["task_ids"] == ids[:2]
    assert first["max_tasks"] == 2
    assert first["status"] == "complete"
    assert first["metrics"]["n_tasks"] == 2
    assert first["inflight_peak"] == 3
    assert not first.get("cancelled")
    assert plan.task_ids == ids  # Executing a slice does not destroy the candidate plan.
    progress = json.loads((Path(first["summary_path"]).parent / "progress.json").read_text())
    assert progress["done"] == progress["total"] == 4
    assert progress["task_ids"] == ids[:2]

    calls.clear()
    next_plan = plan_suite_run(dataset, max_tasks=1, n_attempts=2, suite_run_id=plan.suite_run_id)
    second = await execute_suite_run(next_plan, run_fn=runner, resume=True)
    assert calls == [(ids[2], 0), (ids[2], 1)]
    assert second["task_ids"] == ids[:3]
    assert second["attempts"][:4] == first["attempts"]
    assert second["max_tasks"] == 1

    calls.clear()
    remainder = plan_suite_run(dataset, n_attempts=2, suite_run_id=plan.suite_run_id)
    final = await execute_suite_run(remainder, run_fn=runner, resume=True)
    assert calls == [(ids[3], 0), (ids[3], 1)]
    assert final["task_ids"] == ids
    assert final["max_tasks"] is None
    assert len(final["attempts"]) == 8
    assert final["config_fingerprint"] == first["config_fingerprint"]

    calls.clear()
    no_work = plan_suite_run(dataset, max_tasks=1, n_attempts=2, suite_run_id=plan.suite_run_id)
    settled = await execute_suite_run(no_work, run_fn=runner, resume=True)
    assert not calls
    assert settled["attempts"] == final["attempts"]
    assert settled["task_ids"] == ids


@pytest.mark.asyncio
async def test_partial_task_retry_errors_and_cancel_scope(dataset: Path) -> None:
    calls: list[tuple[str, int]] = []
    plan = plan_suite_run(dataset, max_tasks=1, n_attempts=3, max_concurrent_tasks=1)

    async def interrupted(root, task_id, *, attempt_index=0, **kwargs):  # noqa: ANN001
        if attempt_index == 1:
            raise asyncio.CancelledError
        return 0, SimpleNamespace(status="PASS", score=1.0, evidence_path=None, logs=None)

    with pytest.raises(asyncio.CancelledError):
        await execute_suite_run(plan, run_fn=interrupted)

    async def runner(root, task_id, *, attempt_index=0, **kwargs):  # noqa: ANN001
        calls.append((task_id, attempt_index))
        return 2, SimpleNamespace(status="ERROR", score=None, evidence_path=None, logs=None)

    resumed = await execute_suite_run(plan, run_fn=runner, resume=True)
    assert calls == [("alpha", 1), ("alpha", 2)]
    assert resumed["task_ids"] == ["alpha"]
    assert resumed["tasks"][0]["n"] == 3
    assert [row["status"] for row in resumed["attempts"]] == ["PASS", "ERROR", "ERROR"]
    assert resumed["status"] == "complete"

    calls.clear()
    retried = await execute_suite_run(plan, run_fn=runner, resume=True, retry_errors=True)
    assert calls == [("alpha", 1), ("alpha", 2)]
    assert retried["retried_attempts"] == 2
    assert retried["attempts"][1]["previous"][0]["status"] == "ERROR"

    cancel_plan = plan_suite_run(dataset, max_tasks=2, max_concurrent_tasks=1)

    async def cancel(root, task_id, **kwargs):  # noqa: ANN001
        request_suite_cancel(dataset, cancel_plan.suite_run_id)
        return 0, SimpleNamespace(status="PASS", score=1.0, evidence_path=None, logs=None)

    cancelled = await execute_suite_run(cancel_plan, run_fn=cancel)
    assert cancelled["task_ids"] == ["alpha", "beta"]
    assert len(cancelled["attempts"]) == 2
    assert cancelled["attempts"][1]["error"] == "suite_cancelled"


@pytest.mark.asyncio
async def test_budget_rejects_slot_replacement(dataset: Path) -> None:
    plan = plan_suite_run(dataset, max_tasks=1)
    with pytest.raises(ConfigError, match="cannot be combined"):
        await execute_suite_run(plan, resume=True, replace_slots={("alpha", 0)})
