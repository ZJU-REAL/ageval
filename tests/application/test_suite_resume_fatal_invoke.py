"""Suite resume overwrites a fatal-invoke ERROR in the same Attempt slot."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.application.suite.suite_run import execute_suite_run, plan_suite_run
from ageval.model.errors import FATAL_INVOKE_TITLE

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"


def _fatal_runner(seen: list[bool]):
    async def run(root, task_id, *, attempt_index=0, resume_recorded_invoke_error=False, **kwargs):  # noqa: ANN001
        del kwargs
        seen.append(bool(resume_recorded_invoke_error))
        run_id = "sha256_dead_run_fatal_invoke"
        attempt = Path(root) / ".ageval" / "runs" / run_id
        attempt.mkdir(parents=True, exist_ok=True)
        result = SimpleNamespace(
            status="ERROR",
            score=None,
            evidence_path=str(attempt),
            logs=str(attempt),
            limit=None,
            error={
                "phase": "run",
                "title": FATAL_INVOKE_TITLE,
                "message": "ModelConfigError:chat_http_403:insufficient balance",
            },
            metrics={},
            fork=None,
            replay=None,
        )
        return 2, result

    return run


def _success_same_attempt(seen: list[bool]):
    async def run(root, task_id, *, attempt_index=0, resume_recorded_invoke_error=False, **kwargs):  # noqa: ANN001
        del kwargs
        seen.append(bool(resume_recorded_invoke_error))
        run_id = "sha256_dead_run_fatal_invoke"
        attempt = Path(root) / ".ageval" / "runs" / run_id
        attempt.mkdir(parents=True, exist_ok=True)
        result = SimpleNamespace(
            status="PASS",
            score=1.0,
            evidence_path=str(attempt),
            logs=str(attempt),
            limit=None,
            error=None,
            metrics={},
            fork=None,
            replay=None,
        )
        return 0, result

    return run


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_errors", [False, True])
async def test_fatal_error_is_attached_and_overwritten_without_history(
    retry_errors: bool,
) -> None:
    first_seen: list[bool] = []
    plan = plan_suite_run(SUITE, task_id="alpha", n_attempts=1)
    first = await execute_suite_run(plan, run_fn=_fatal_runner(first_seen))
    old = first["attempts"][0]
    assert old["status"] == "ERROR"
    assert old["run_id"] == "sha256_dead_run_fatal_invoke"
    assert first_seen == [False]

    seen: list[bool] = []
    plan2 = plan_suite_run(
        SUITE,
        task_id="alpha",
        n_attempts=1,
        suite_run_id=first["suite_run_id"],
    )
    second = await execute_suite_run(
        plan2,
        run_fn=_success_same_attempt(seen),
        resume=True,
        retry_errors=retry_errors,
    )
    assert seen == [True]
    assert len(second["attempts"]) == 1
    current = second["attempts"][0]
    assert current["run_id"] == old["run_id"]
    assert current["status"] == "PASS"
    assert "previous" not in current
    assert "amended" not in second
    assert second["new_attempts"] == 1
    assert second["skipped_attempts"] == 0
    assert second.get("retried_attempts", 0) == 0


@pytest.mark.asyncio
async def test_in_place_resume_preserves_an_existing_previous_chain() -> None:
    plan = plan_suite_run(SUITE, task_id="alpha", n_attempts=1)
    first = await execute_suite_run(plan, run_fn=_fatal_runner([]))
    summary_path = Path(first["summary_path"])
    doc = json.loads(summary_path.read_text(encoding="utf-8"))
    doc["attempts"][0]["previous"] = [
        {
            "run_id": "older",
            "status": "ERROR",
            "score": None,
            "attempt_index": 0,
            "replaced_at": "t0",
        }
    ]
    summary_path.write_text(
        json.dumps(doc, indent=2) + "\n",
        encoding="utf-8",
    )

    plan2 = plan_suite_run(
        SUITE,
        task_id="alpha",
        n_attempts=1,
        suite_run_id=first["suite_run_id"],
    )
    second = await execute_suite_run(
        plan2,
        run_fn=_success_same_attempt([]),
        resume=True,
    )
    current = second["attempts"][0]
    assert current["run_id"] == "sha256_dead_run_fatal_invoke"
    assert current["previous"][0]["run_id"] == "older"
    assert second["amended"] is True
