"""Public replay on environment local: real exec, no solver call, source untouched."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ageval.cli.main import app

ROOT = Path(__file__).resolve().parents[2]

_DATASET = """\
format: ageval.dataset/1
dataset_id: test/replay-local
version: "0.1.0"
description: Terminal action replay on a local box.
tasks:
  root: tasks
"""

_PROFILES = """\
format: ageval.profiles/1
environment: local
agent_profiles:
  solver:
    executor: miniswe
    model:
      id: openai/replay
      api: chat
    api_key: ${SOLVER_API_KEY}
    base_url: http://127.0.0.1:9/v1
    extensions:
      - plugin: miniswe
      - plugin: local
"""

_TASK = """\
format: ageval.task/1
task_id: hello
parameters:
  seed: 1
agent_profiles:
  - id: solver
limits:
  wall_time_seconds: 60
  environment_seconds: 30
  evaluate_seconds: 30
  agent_invocations: 1
"""

_EVAL = """\
def evaluate(inputs):
    del inputs
    return {"status": "FAIL", "score": 0.0, "metrics": {}}
"""

_RUN = """\
from ageval_sdk import RunContext, RunTerminal

async def run(ctx: RunContext) -> RunTerminal:
    del ctx
    return RunTerminal.completed("unused")
"""


def _install(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    from ageval.plugins import bootstrap as boot
    from ageval.plugins.registry import reset_global_registry
    from ageval.plugins.store import install_from_path

    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    monkeypatch.setenv("SOLVER_API_KEY", "ci-solver-locator")
    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()
    install_from_path(ROOT / "plugins" / "miniswe")


def _dataset(root: Path, seed: str) -> None:
    (root / "tasks" / "hello" / "data").mkdir(parents=True)
    (root / "tasks" / "hello" / "evaluation").mkdir()
    (root / "ageval.yaml").write_text(_DATASET, encoding="utf-8")
    (root / "profiles.yaml").write_text(_PROFILES, encoding="utf-8")
    (root / "tasks" / "hello" / "task.yaml").write_text(_TASK, encoding="utf-8")
    (root / "tasks" / "hello" / "run.py").write_text(_RUN, encoding="utf-8")
    (root / "tasks" / "hello" / "evaluator.py").write_text(_EVAL, encoding="utf-8")
    (root / "tasks" / "hello" / "evaluation" / "gold.txt").write_text(
        "secret-gold\n", encoding="utf-8"
    )
    (root / "tasks" / "hello" / "data" / "note.txt").write_text(seed, encoding="utf-8")


def _activity(attempt: Path, command: str, output: str, exit_code: int) -> None:
    from ageval.evidence.activity import ActivityLog
    from ageval.evidence.store import ACTIVITY_LOG_REL

    log = ActivityLog.open(attempt / ACTIVITY_LOG_REL)
    log.append(
        request_id="attempt",
        kind="attempt",
        status="completed",
        payload={
            "run_id": "run",
            "trial_id": "trial",
            "attempt_id": attempt.name,
            "task_id": "hello",
            "attempt_index": 0,
            "suite_run_id": None,
            "locked_config_digest": "sha256:source",
            "environment_kind": "local",
            "environment_nonce": "n",
            "environment_handle": None,
        },
    )
    log.append(
        request_id="tool_bash_1",
        kind="tool_call",
        status="in_flight",
        payload={
            "session_id": "s",
            "invoke_request_id": "req",
            "tool_call_id": "bash_1",
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
        request_id="tool_bash_1",
        kind="tool_call",
        status="completed",
        payload={
            "session_id": "s",
            "invoke_request_id": "req",
            "tool_call_id": "bash_1",
            "outcome": "ok" if exit_code == 0 else "error",
            "exit_code": exit_code,
            "content": output,
            "stderr": None,
            "raw_output": None,
            "checkpoint_seq": None,
        },
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_replays_bash_without_a_model_or_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, tmp_path / "home")
    dataset = tmp_path / "dataset"
    _dataset(dataset, "hello\n")
    locked = CliRunner().invoke(
        app,
        ["lock", str(dataset), "--task", "hello", "--profiles", str(dataset / "profiles.yaml")],
    )
    assert locked.exit_code == 0, locked.stderr
    source = dataset / ".ageval" / "runs" / "source-attempt"
    source.mkdir(parents=True)
    (source / "lock.json").write_text(locked.stdout, encoding="utf-8")
    _activity(source, "cat note.txt", "hello\n", 0)
    before = _digest(source / "activity.jsonl")
    result = CliRunner().invoke(
        app,
        ["replay", str(dataset), "--run", "source-attempt", "--keep-recovery-state", "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "matched"
    assert report["source_attempt_id"] == "source-attempt"
    assert report["attempt_id"] not in {"", "source-attempt"}
    assert report["evaluator_status"] is None
    assert _digest(source / "activity.jsonl") == before
    child = dataset / ".ageval" / "runs" / report["attempt_id"]
    sealed = json.loads((child / "result.json").read_text(encoding="utf-8"))
    assert sealed["status"] != "PASS"
    assert sealed["error"]["title"] == "not_evaluated"
    assert sealed["replay"]["status"] == "matched"
    assert sealed["agent_invocations"] == 0
    activity = (child / "activity.jsonl").read_text(encoding="utf-8")
    assert "model_turn" not in activity
    assert "hello" in (child / "replay" / "observations.jsonl").read_text(encoding="utf-8")
    assert "secret-gold" not in activity


def test_evaluate_grades_new_artifacts_and_replay_match_is_not_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, tmp_path / "home")
    dataset = tmp_path / "dataset"
    _dataset(dataset, "hello\n")
    locked = CliRunner().invoke(
        app,
        ["lock", str(dataset), "--task", "hello", "--profiles", str(dataset / "profiles.yaml")],
    )
    assert locked.exit_code == 0, locked.stderr
    source = dataset / ".ageval" / "runs" / "source-attempt"
    source.mkdir(parents=True)
    (source / "lock.json").write_text(locked.stdout, encoding="utf-8")
    _activity(source, "cat note.txt", "hello\n", 0)
    result = CliRunner().invoke(
        app,
        ["replay", str(dataset), "--run", "source-attempt", "--evaluate", "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "matched"
    assert report["evaluator_status"] == "FAIL"
    child = dataset / ".ageval" / "runs" / report["attempt_id"]
    sealed = json.loads((child / "result.json").read_text(encoding="utf-8"))
    assert sealed["status"] == "FAIL"
    assert sealed["replay"]["evaluated"] is True
