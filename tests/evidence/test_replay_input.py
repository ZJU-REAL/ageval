"""Replay input manifest: completeness, redaction, and identity preflight."""

from __future__ import annotations

import json
from pathlib import Path

from ageval.evidence.activity import ActivityLog
from ageval.evidence.checkpoints import prune_recovery_bundle
from ageval.evidence.replay_input import (
    build_replay_input,
    compare_identities,
    diagnose_replay,
    normalize_output,
    write_replay_input,
)
from ageval.evidence.store import ACTIVITY_LOG_REL, REPLAY_INPUT_REL
from ageval.plugins.base import BaseExecutor


def _log(path: Path) -> ActivityLog:
    log = ActivityLog.open(path)
    log.append(
        request_id="attempt",
        kind="attempt",
        status="completed",
        payload={
            "run_id": "run_1",
            "trial_id": "trial_1",
            "attempt_id": path.parent.name,
            "task_id": "hello",
            "attempt_index": 0,
            "suite_run_id": None,
            "locked_config_digest": "sha256:abc",
            "environment_kind": "local",
            "environment_nonce": "n",
            "environment_handle": None,
        },
    )
    return log


def _bash(
    log: ActivityLog, call_id: str, command: str, *, exit_code: int = 0, output: str = "ok"
) -> None:
    log.append(
        request_id=f"tool_{call_id}",
        kind="tool_call",
        status="in_flight",
        payload={
            "session_id": "s",
            "invoke_request_id": "req",
            "tool_call_id": call_id,
            "tool_name": "bash",
            "tool_kind": "execute",
            "arguments": {"command": command},
            "replay_safe": False,
            "system_effect": False,
            "timeout_sec": 30.0,
            "deadline_utc": None,
        },
    )
    log.append(
        request_id=f"tool_{call_id}",
        kind="tool_call",
        status="completed",
        payload={
            "session_id": "s",
            "invoke_request_id": "req",
            "tool_call_id": call_id,
            "outcome": "ok" if exit_code == 0 else "error",
            "exit_code": exit_code,
            "content": output,
            "stderr": None,
            "raw_output": None,
            "checkpoint_seq": None,
        },
    )


def _ids(**overrides: str) -> dict[str, str]:
    base = {
        "task_id": "hello",
        "dataset_id": "demo",
        "dataset_version": "1",
        "environment": "local",
        "locked_config_digest": "sha256:abc",
        "eval_digest": "sha256:eval",
        "image": "",
    }
    base.update(overrides)
    return base


def _bash_classifier(pairs):
    actions = []
    missing = []
    for index, pair in enumerate(pairs, start=1):
        command = ""
        arguments = pair.get("arguments")
        if isinstance(arguments, dict):
            command = str(arguments.get("command") or "")
        row_missing = []
        if "[REDACTED" in command:
            row_missing.append("command_redacted")
        if pair.get("tool_name") != "bash":
            row_missing.append("unsupported_action")
        actions.append(
            {
                "ordinal": index,
                "tool_call_id": pair.get("tool_call_id"),
                "tool_name": pair.get("tool_name"),
                "arguments": {"command": command, "cwd": None},
                "timeout_sec": pair.get("timeout_sec"),
                "recorded_exit_code": pair.get("recorded_exit_code"),
                "recorded_output": pair.get("recorded_output"),
                "executable": not row_missing,
                "missing": row_missing,
            }
        )
        missing.extend(row_missing)
    return {
        "tool_semantics": "bash",
        "tool_semantics_version": "miniswe.bash/1",
        "actions": actions,
        "missing": missing,
    }


def test_bash_program_is_replayable(tmp_path: Path) -> None:
    log = _log(tmp_path / "att" / ACTIVITY_LOG_REL)
    _bash(log, "bash_1", "echo hi", output="hi\n")
    document = build_replay_input(log.records, _ids(), _bash_classifier)
    assert document["replayable"] is True
    actions = document["actions"]
    assert isinstance(actions, list)
    assert actions[0]["arguments"] == {"command": "echo hi", "cwd": None}
    assert actions[0]["executable"] is True


def test_redacted_command_is_not_replayable(tmp_path: Path) -> None:
    log = _log(tmp_path / "att" / ACTIVITY_LOG_REL)
    _bash(log, "bash_1", "echo [REDACTED:secret]")
    document = build_replay_input(log.records, _ids(), _bash_classifier)
    assert document["replayable"] is False
    missing = document["missing"]
    assert isinstance(missing, list)
    assert "command_redacted" in missing


def test_unsupported_action_is_not_skipped(tmp_path: Path) -> None:
    log = _log(tmp_path / "att" / ACTIVITY_LOG_REL)
    log.append(
        request_id="tool_browser",
        kind="tool_call",
        status="in_flight",
        payload={
            "session_id": "s",
            "invoke_request_id": "req",
            "tool_call_id": "browser_1",
            "tool_name": "browser",
            "tool_kind": "domain",
            "arguments": {"url": "https://example.test"},
            "replay_safe": False,
            "system_effect": False,
            "timeout_sec": None,
            "deadline_utc": None,
        },
    )
    log.append(
        request_id="tool_browser",
        kind="tool_call",
        status="completed",
        payload={
            "session_id": "s",
            "invoke_request_id": "req",
            "tool_call_id": "browser_1",
            "outcome": "ok",
            "exit_code": 0,
            "content": "",
            "stderr": None,
            "raw_output": None,
            "checkpoint_seq": None,
        },
    )
    document = build_replay_input(log.records, _ids(), _bash_classifier)
    assert document["replayable"] is False
    missing = document["missing"]
    assert isinstance(missing, list)
    assert "unsupported_action" in missing


def test_executor_without_adapter_states_the_gap(tmp_path: Path) -> None:
    log = _log(tmp_path / "att" / ACTIVITY_LOG_REL)
    _bash(log, "bash_1", "echo hi")
    document = build_replay_input(log.records, _ids(), BaseExecutor.classify_replay_actions)
    assert document["replayable"] is False
    assert document["missing"] == ["terminal_replay_unsupported"]


def test_missing_bundle_is_diagnosed_before_effects(tmp_path: Path) -> None:
    diagnosis = diagnose_replay(tmp_path / "missing", _ids(), _bash_classifier)
    assert diagnosis.replayable is False
    assert diagnosis.error == "recovery_state_missing"


def test_image_mismatch_blocks_replay(tmp_path: Path) -> None:
    attempt = tmp_path / "att"
    log = _log(attempt / ACTIVITY_LOG_REL)
    _bash(log, "bash_1", "echo hi")
    (attempt / "lock.json").write_text(
        json.dumps(
            {
                "task_id": "hello",
                "dataset_id": "demo",
                "environment": "docker",
                "eval_digest": "sha256:eval",
            }
        ),
        encoding="utf-8",
    )
    write_replay_input(
        attempt,
        build_replay_input(
            log.records,
            _ids(environment="docker", image="ghcr.io/example/attempt:1"),
            _bash_classifier,
        ),
    )
    diagnosis = diagnose_replay(
        attempt,
        _ids(environment="docker", image="ghcr.io/example/attempt:2"),
        _bash_classifier,
    )
    assert diagnosis.replayable is False
    assert "image" in diagnosis.mismatches


def test_timing_text_is_not_a_normalized_difference() -> None:
    assert normalize_output("done in 1.2s pid=9") == normalize_output("done in 40s PID: 100")
    assert normalize_output("hello") != normalize_output("goodbye")


def test_prune_removes_replay_input_with_the_bundle(tmp_path: Path) -> None:
    (tmp_path / ACTIVITY_LOG_REL).write_text("", encoding="utf-8")
    (tmp_path / REPLAY_INPUT_REL).write_text("{}\n", encoding="utf-8")
    prune_recovery_bundle(tmp_path)
    assert not (tmp_path / REPLAY_INPUT_REL).is_file()
    assert not (tmp_path / ACTIVITY_LOG_REL).is_file()


def test_identity_compare_ignores_unrecorded_eval_digest() -> None:
    assert compare_identities(_ids(eval_digest=""), _ids(eval_digest="sha256:now")) == ()
    assert compare_identities(_ids(), _ids(task_id="other")) == ("task_id",)
