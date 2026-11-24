"""Suite preempt: stop new units, leave in-flight rows suspended, resume them."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.application.suite.suite_run import (
    _existing_attempt_keys,
    _is_suspended_row,
    execute_suite_run,
    is_suite_cancel_requested,
    is_suite_preempt_requested,
    plan_suite_run,
    request_suite_preempt,
)
from ageval.runtime.preempt import PREEMPT_SCHEMA, read_suite_preempt

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"


def _pass(task_id: str, generation: str) -> SimpleNamespace:
    return SimpleNamespace(
        status="PASS",
        score=1.0,
        evidence_path=None,
        logs=None,
        error=None,
        run_id_hint=f"sha256_dead_run_{task_id}_{generation}",
    )


def _suspended(task_id: str) -> SimpleNamespace:
    run_id = f"sha256_dead_run_{task_id}_live"
    return SimpleNamespace(
        status="suspended",
        score=None,
        evidence_path=run_id,
        logs=run_id,
        error=None,
        preempted=True,
    )


@pytest.mark.asyncio
async def test_preempt_stops_new_units_and_keeps_inflight_unsealed() -> None:
    plan = plan_suite_run(SUITE, n_attempts=1, max_concurrent_tasks=1)
    plan.task_ids = ["alpha", "beta", "gamma"]
    calls: list[str] = []

    async def runner(root, task_id, *, overrides=None, profiles_path=None, **kwargs):  # noqa: ANN001
        del root, overrides, profiles_path, kwargs
        calls.append(task_id)
        if task_id == "alpha":
            request_suite_preempt(plan.dataset_root, plan.suite_run_id)
            await asyncio.sleep(0.05)
            return 0, _suspended(task_id)
        await asyncio.sleep(0.02)
        return 0, _pass(task_id, "1")

    summary = await execute_suite_run(plan, run_fn=runner)
    assert summary.get("preempted") is True
    assert summary.get("status") == "suspended"
    assert summary.get("cancelled") is not True
    assert is_suite_preempt_requested(plan.dataset_root, plan.suite_run_id)
    assert not is_suite_cancel_requested(plan.dataset_root, plan.suite_run_id)
    assert calls == ["alpha"]
    suspended = [row for row in summary["attempts"] if row.get("phase") == "preempted"]
    assert len(suspended) == 1
    assert suspended[0]["task_id"] == "alpha"
    assert suspended[0]["status"] == "suspended"
    assert suspended[0]["error"] is None
    assert suspended[0]["run_id"] == "sha256_dead_run_alpha_live"
    placeholders = [row for row in summary["attempts"] if row.get("phase") == "cancelled"]
    assert {row["task_id"] for row in placeholders} == {"beta", "gamma"}
    assert all(row.get("error") == "suite_cancelled" for row in placeholders)
    progress = json.loads(
        (
            plan.dataset_root / ".ageval" / "suite-runs" / plan.suite_run_id / "progress.json"
        ).read_text(encoding="utf-8")
    )
    assert progress["status"] == "suspended"
    assert progress["preempt_requested"] is True
    request = read_suite_preempt(plan.dataset_root, plan.suite_run_id)
    assert request is not None
    assert request.tasks is None
    doc = json.loads(
        (
            plan.dataset_root / ".ageval" / "suite-runs" / plan.suite_run_id / "preempt.requested"
        ).read_text(encoding="utf-8")
    )
    assert doc["schema"] == PREEMPT_SCHEMA


@pytest.mark.asyncio
async def test_named_task_preempt_lets_other_tasks_finish() -> None:
    plan = plan_suite_run(SUITE, n_attempts=1, max_concurrent_tasks=1)
    plan.task_ids = ["alpha", "beta", "gamma"]
    calls: list[str] = []

    async def runner(root, task_id, *, overrides=None, profiles_path=None, **kwargs):  # noqa: ANN001
        del root, overrides, profiles_path, kwargs
        calls.append(task_id)
        if task_id == "alpha":
            request_suite_preempt(plan.dataset_root, plan.suite_run_id, tasks=["beta"])
        return 0, _pass(task_id, "1")

    summary = await execute_suite_run(plan, run_fn=runner)
    assert calls == ["alpha", "gamma"]
    by_task = {row["task_id"]: row for row in summary["attempts"]}
    assert by_task["alpha"]["status"] == "PASS"
    assert by_task["gamma"]["status"] == "PASS"
    assert by_task["beta"]["phase"] == "cancelled"
    assert by_task["beta"]["error"] == "suite_cancelled"
    assert summary["status"] == "suspended"
    stored = read_suite_preempt(plan.dataset_root, plan.suite_run_id)
    assert stored is not None and stored.tasks == frozenset({"beta"})


@pytest.mark.asyncio
async def test_resume_clears_preempt_and_reruns_suspended_slot() -> None:
    plan = plan_suite_run(SUITE, n_attempts=1, max_concurrent_tasks=1)
    plan.task_ids = ["alpha", "beta"]

    async def runner1(root, task_id, *, overrides=None, profiles_path=None, **kwargs):  # noqa: ANN001
        del root, overrides, profiles_path, kwargs
        if task_id == "alpha":
            request_suite_preempt(plan.dataset_root, plan.suite_run_id)
            return 0, _suspended(task_id)
        return 0, _pass(task_id, "1")

    first = await execute_suite_run(plan, run_fn=runner1)
    suite_id = first["suite_run_id"]
    alpha = next(row for row in first["attempts"] if row["task_id"] == "alpha")
    assert _is_suspended_row(alpha)
    assert ("alpha", 0) not in _existing_attempt_keys(first["attempts"])
    assert ("beta", 0) not in _existing_attempt_keys(first["attempts"])

    plan2 = plan_suite_run(SUITE, n_attempts=1, max_concurrent_tasks=1, suite_run_id=suite_id)
    plan2.task_ids = ["alpha", "beta"]
    seen: list[tuple[str, bool]] = []

    async def runner2(root, task_id, *, overrides=None, profiles_path=None, **kwargs):  # noqa: ANN001
        del root, overrides, profiles_path
        seen.append((task_id, bool(kwargs.get("recover_unsealed"))))
        return 0, _pass(task_id, "2")

    second = await execute_suite_run(plan2, run_fn=runner2, resume=True)
    assert second.get("resumed") is True
    assert second.get("status") == "complete"
    assert not is_suite_preempt_requested(plan.dataset_root, suite_id)
    assert ("alpha", True) in seen
    assert "beta" in {task for task, _recovered in seen}
    assert all(row.get("status") == "PASS" for row in second["attempts"])
    assert not any(row.get("phase") == "preempted" for row in second["attempts"])


def test_drain_cancel_file_is_distinct() -> None:
    plan = plan_suite_run(SUITE, n_attempts=1, max_concurrent_tasks=1)
    path = request_suite_preempt(plan.dataset_root, plan.suite_run_id, tasks=["alpha"])
    assert path.name == "preempt.requested"
    assert not (path.parent / "cancel.requested").exists()
