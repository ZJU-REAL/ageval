"""Suite metric aggregation unit tests (#23 Phase A)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.application.suite.suite_metrics import (
    MISSING_SCORE_AS,
    aggregate_task_metrics,
    task_refs_for_summary,
)
from ageval.application.suite.suite_run import execute_suite_run, plan_suite_run

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"


def test_aggregate_empty() -> None:
    m = aggregate_task_metrics([])
    assert m["n_tasks"] == 0
    assert m["pass_rate"] == 0.0
    assert m["mean_score"] == 0.0
    assert m["missing_score_as"] == MISSING_SCORE_AS


def test_aggregate_pass_rate_and_mean() -> None:
    rows = [
        {"task_id": "a", "status": "PASS", "score": 1.0},
        {"task_id": "b", "status": "FAIL", "score": 0.0},
        {"task_id": "c", "status": "PASS", "score": 0.5},
        {"task_id": "d", "status": "ERROR", "score": None},
    ]
    m = aggregate_task_metrics(rows)
    assert m["n_tasks"] == 4
    assert m["n_pass"] == 2
    assert m["n_fail"] == 1
    assert m["n_error"] == 1
    assert m["pass_rate"] == pytest.approx(0.5)
    # scores: 1.0, 0.0, 0.5, 0.0 (ERROR→0) → mean 0.375
    assert m["mean_score"] == pytest.approx(0.375)


def test_missing_score_counts_as_zero() -> None:
    rows = [
        {"status": "PASS", "score": None},
        {"status": "FAIL"},  # no score key
        {"status": "PASS", "score": "bad"},  # non-numeric
    ]
    m = aggregate_task_metrics(rows)
    assert m["mean_score"] == 0.0
    assert m["pass_rate"] == pytest.approx(2 / 3)


def test_error_forces_zero_even_with_score() -> None:
    m = aggregate_task_metrics([{"status": "ERROR", "score": 0.9}])
    assert m["mean_score"] == 0.0
    assert m["n_error"] == 1


def test_task_refs_shape() -> None:
    refs = task_refs_for_summary(
        [
            {"task_id": "a", "status": "pass", "score": 1, "run_id": "r1"},
            {"task_id": "b", "status": "FAIL", "score": None, "run_id": None},
        ]
    )
    assert refs[0] == {
        "task_id": "a",
        "status": "PASS",
        "score": 1.0,
        "run_id": "r1",
        "error": None,
        "limit": None,
    }
    assert refs[1]["status"] == "FAIL"
    assert refs[1]["score"] is None


def test_bool_score_not_numeric() -> None:
    """bool is a subclass of int; must not become 1.0/0.0 in refs or mean."""
    rows = [
        {"task_id": "a", "status": "PASS", "score": True},
        {"task_id": "b", "status": "FAIL", "score": False},
    ]
    m = aggregate_task_metrics(rows)
    assert m["mean_score"] == 0.0
    refs = task_refs_for_summary(rows)
    assert refs[0]["score"] is None
    assert refs[1]["score"] is None


@pytest.mark.asyncio
async def test_suite_summary_includes_metrics() -> None:
    plan = plan_suite_run(SUITE, max_concurrent_tasks=2)
    plan.task_ids = ["alpha", "beta", "gamma"]

    async def runner(root, task_id, *, overrides=None, profiles_path=None, **kwargs):  # noqa: ANN001
        result = SimpleNamespace(
            status="PASS",
            score=1.0,
            metrics={"x": 1},
            evidence_path=None,
            logs=None,
        )
        return 0, result

    summary = await execute_suite_run(plan, run_fn=runner)
    assert "metrics" in summary
    assert summary["metrics"]["pass_rate"] == pytest.approx(1.0)
    assert summary["metrics"]["mean_score"] == pytest.approx(1.0)
    assert summary["metrics"]["n_tasks"] == 3
    assert "suite-level PASS" not in str(summary.get("metrics"))
    assert summary["note"].startswith("per-task")
    assert "PASS" not in summary or summary.get("status") is None
    # No suite PASS authority field
    assert "pass" not in summary or summary["pass"] is not True  # type: ignore[comparison-overlap]
    assert "verdict" not in summary

    path = Path(summary["summary_path"])
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert disk["metrics"]["n_pass"] == 3
    assert len(disk["task_refs"]) == 3
    assert disk["tasks"][0]["metrics"] == {"x": 1}
