"""Fork rows stay out of default pass@k samples."""

from __future__ import annotations

from ageval.application.suite.suite_metrics import count_passes, rollup_task_from_attempts
from ageval.evidence.fork_cuts import fork_marker


def test_count_passes_skips_fork_rows() -> None:
    rows = [
        {"status": "PASS", "run_id": "fresh"},
        {"status": "PASS", "run_id": "child", "fork": {"parent_attempt_id": "parent"}},
        {"status": "FAIL", "run_id": "other"},
    ]
    assert count_passes(rows) == (2, 1)
    rolled = rollup_task_from_attempts("demo", rows)
    assert rolled["n"] == 2
    assert rolled["c"] == 1
    assert rolled["status"] == "PASS"
    assert rolled["run_id"] == "fresh"


def test_fork_marker_reads_child_result_without_parent() -> None:
    marker = fork_marker(
        {
            "status": "PASS",
            "fork": {
                "parent_attempt_id": "attempt-parent",
                "checkpoint_seq": 6,
                "source_model": "model-a",
                "continuation_model": "model-b",
            },
        },
        {},
    )
    assert marker is not None
    assert marker["parent_attempt_id"] == "attempt-parent"
    assert marker["source_model"] == "model-a"
    assert marker["continuation_model"] == "model-b"
    assert fork_marker({"status": "PASS"}, {}) is None
