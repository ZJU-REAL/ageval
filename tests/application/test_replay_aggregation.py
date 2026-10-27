"""Replay rows stay out of default pass@k samples and keep child provenance."""

from __future__ import annotations

from ageval.application.suite.suite_metrics import count_passes
from ageval.evidence.replay_input import replay_marker


def test_count_passes_skips_replay_rows() -> None:
    rows = [
        {"status": "PASS", "run_id": "fresh"},
        {"status": "PASS", "run_id": "child", "replay": {"parent_attempt_id": "parent"}},
        {"status": "FAIL", "run_id": "other"},
    ]
    assert count_passes(rows) == (2, 1)


def test_replay_marker_survives_without_the_parent_archive() -> None:
    marker = replay_marker(
        {
            "status": "ERROR",
            "replay": {
                "parent_attempt_id": "attempt-parent",
                "status": "diverged",
                "first_divergence": {"field": "exit_code", "ordinal": 2, "tool_call_id": "bash_2"},
            },
        },
        {},
    )
    assert marker is not None
    assert marker["parent_attempt_id"] == "attempt-parent"
    assert marker["field"] == "exit_code"
    assert marker["ordinal"] == 2
    assert replay_marker({"status": "PASS"}, {}) is None
