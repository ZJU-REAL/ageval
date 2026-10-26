"""A reopened activity log redacts with the evidence store's sentinels."""

from __future__ import annotations

from pathlib import Path

from ageval.attempt.recover import bind_sentinels, load_activity
from ageval.evidence.activity import ActivityLog
from ageval.evidence.store import ACTIVITY_LOG_REL


def test_reopened_log_redacts_evidence_sentinels(tmp_path: Path) -> None:
    attempt = tmp_path / "attempt_a"
    attempt.mkdir()
    secret = "CANARYVALUE123456"
    opened = ActivityLog.open(attempt / ACTIVITY_LOG_REL)
    opened.append(
        request_id="att",
        kind="attempt",
        status="completed",
        payload={
            "run_id": "run",
            "trial_id": "trial",
            "attempt_id": "attempt_a",
            "task_id": "task",
            "attempt_index": 0,
            "suite_run_id": None,
            "locked_config_digest": "sha256:abc",
            "environment_kind": "local",
            "environment_nonce": "nce_1",
            "environment_handle": None,
        },
    )
    loaded = load_activity(attempt)
    assert loaded.sentinels == ()
    bind_sentinels(loaded, [secret])
    loaded.append(
        request_id="req_1",
        kind="invoke",
        status="in_flight",
        payload={
            "session_id": "sess",
            "turn_index": 1,
            "prompt": f"use {secret}",
            "tools_digest": None,
            "messages_digest": None,
            "explicit_messages": None,
        },
    )
    text = (attempt / ACTIVITY_LOG_REL).read_text(encoding="utf-8")
    assert secret not in text
    assert "[REDACTED:secret]" in text
