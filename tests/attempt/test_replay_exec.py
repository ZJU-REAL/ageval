"""Recorded terminal actions run again on a real local box."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from tests.helpers.box import local_box

from ageval.environments.protocol import WORKSPACE_PATH
from ageval.evidence.activity import ActivityLog
from ageval.evidence.store import ACTIVITY_LOG_REL
from ageval.plugins.protocol import WinnerRef
from ageval.plugins.slots import EXECUTOR


class _Bash:
    @classmethod
    async def dispatch_terminal_action(cls, host, action, placement):
        arguments = action["arguments"]
        result = await host.exec(
            ["bash", "-lc", arguments["command"]],
            cwd=placement.workdir,
            timeout_sec=action.get("timeout_sec") or 30,
        )
        output = f"{result.stdout}{result.stderr}"
        return {
            "exit_code": int(result.exit_code),
            "output": output,
            "raw_output": output,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }


def _ctx(tmp_path: Path, actions: list[dict[str, object]]) -> SimpleNamespace:
    host = local_box(tmp_path / "box")
    asyncio.run(host.start())
    note = host.host_path(f"{WORKSPACE_PATH}/note.txt")
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("hello\n", encoding="utf-8")
    log = ActivityLog.open(tmp_path / "child" / ACTIVITY_LOG_REL)
    log.append(
        request_id="attempt",
        kind="attempt",
        status="completed",
        payload={
            "run_id": "run",
            "trial_id": "trial",
            "attempt_id": "child",
            "task_id": "hello",
            "attempt_index": 0,
            "suite_run_id": None,
            "locked_config_digest": "sha256:child",
            "environment_kind": "local",
            "environment_nonce": "n",
            "environment_handle": None,
        },
    )
    evidence = SimpleNamespace(
        root=tmp_path / "child",
        path=lambda rel: tmp_path / "child" / rel,
    )
    (tmp_path / "child").mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        host=host,
        activity=log,
        evidence=evidence,
        lock=SimpleNamespace(digest="sha256:child", resolved_references={}),
        bindings=SimpleNamespace(
            winners={EXECUTOR: WinnerRef(plugin_id="bash", impl=_Bash, priority=1, source="test")}
        ),
        replay_plan={
            "tool_semantics": "bash",
            "tool_semantics_version": "miniswe.bash/1",
            "identities": {"locked_config_digest": "sha256:source"},
            "actions": actions,
        },
        replay_source_id="source",
        replay_source_dir=tmp_path / "source",
        replay_provenance=None,
    )


def test_replay_executes_and_ignores_recorded_stdout(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        [
            {
                "ordinal": 1,
                "tool_call_id": "bash_1",
                "executable": True,
                "arguments": {"command": "cat note.txt", "cwd": None},
                "timeout_sec": 30,
                "recorded_exit_code": 0,
                "recorded_output": "stale\n",
            }
        ],
    )
    from ageval.attempt.replay_exec import execute_recorded_actions

    outcome = asyncio.run(execute_recorded_actions(ctx))
    assert outcome["ok"] is True
    assert ctx.replay_provenance["status"] == "diverged"
    assert ctx.replay_provenance["first_divergence"]["field"] == "output"
    assert "hello" in (tmp_path / "child" / "replay" / "observations.jsonl").read_text(
        encoding="utf-8"
    )
    assert not any(record.kind == "model_turn" for record in ctx.activity.records)


def test_timing_text_is_not_a_divergence(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        [
            {
                "ordinal": 1,
                "tool_call_id": "bash_1",
                "executable": True,
                "arguments": {"command": "printf 'done in 2s\\n'", "cwd": None},
                "timeout_sec": 30,
                "recorded_exit_code": 0,
                "recorded_output": "done in 1.2s\n",
            }
        ],
    )
    from ageval.attempt.replay_exec import execute_recorded_actions

    asyncio.run(execute_recorded_actions(ctx))
    assert ctx.replay_provenance["status"] == "matched"
    assert "first_divergence" not in ctx.replay_provenance


def test_changed_declared_artifact_is_the_first_divergence(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        [
            {
                "ordinal": 1,
                "tool_call_id": "bash_1",
                "executable": True,
                "arguments": {"command": "printf live > out.txt", "cwd": None},
                "timeout_sec": 30,
                "recorded_exit_code": 0,
                "recorded_output": "",
            }
        ],
    )
    ctx.lock.resolved_references = {
        "artifacts": [{"id": "out", "path": "artifacts/out.txt", "kind": "file"}]
    }
    source = tmp_path / "source" / "task-artifacts"
    child = tmp_path / "child" / "task-artifacts"
    source.mkdir(parents=True)
    child.mkdir(parents=True)
    (source / "out.txt").write_text("recorded\n", encoding="utf-8")
    (child / "out.txt").write_text("live\n", encoding="utf-8")
    from ageval.attempt.replay_exec import execute_recorded_actions, note_artifact_divergence

    asyncio.run(execute_recorded_actions(ctx))
    assert ctx.replay_provenance["status"] == "matched"
    note_artifact_divergence(ctx)
    assert ctx.replay_provenance["status"] == "diverged"
    assert ctx.replay_provenance["first_divergence"]["field"] == "artifact"
    assert ctx.replay_provenance["first_divergence"]["artifact_id"] == "out"
    wrote = ctx.host.host_path(f"{WORKSPACE_PATH}/out.txt")
    assert wrote.read_text(encoding="utf-8") == "live"


def test_missing_child_artifact_is_a_divergence(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        [
            {
                "ordinal": 1,
                "tool_call_id": "bash_1",
                "executable": True,
                "arguments": {"command": "true", "cwd": None},
                "timeout_sec": 30,
                "recorded_exit_code": 0,
                "recorded_output": "",
            }
        ],
    )
    ctx.lock.resolved_references = {
        "artifacts": [{"id": "out", "path": "artifacts/out.txt", "kind": "file"}]
    }
    source = tmp_path / "source" / "task-artifacts"
    source.mkdir(parents=True)
    (source / "out.txt").write_text("recorded\n", encoding="utf-8")
    from ageval.attempt.replay_exec import execute_recorded_actions, note_artifact_divergence

    asyncio.run(execute_recorded_actions(ctx))
    note_artifact_divergence(ctx)
    assert ctx.replay_provenance["first_divergence"]["field"] == "artifact"


def test_reproduced_nonzero_exit_is_a_match(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        [
            {
                "ordinal": 1,
                "tool_call_id": "bash_1",
                "executable": True,
                "arguments": {"command": "exit 1", "cwd": None},
                "timeout_sec": 30,
                "recorded_exit_code": 1,
                "recorded_output": "",
            }
        ],
    )
    from ageval.attempt.replay_exec import execute_recorded_actions

    asyncio.run(execute_recorded_actions(ctx))
    assert ctx.replay_provenance["status"] == "matched"
    assert ctx.replay_provenance["reproduced_failure"] is True


def test_reproduced_failure_matches_and_stops_later_actions(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        [
            {
                "ordinal": 1,
                "tool_call_id": "bash_1",
                "executable": True,
                "arguments": {"command": "exit 1", "cwd": None},
                "timeout_sec": 30,
                "recorded_exit_code": 1,
                "recorded_output": "",
            },
            {
                "ordinal": 2,
                "tool_call_id": "bash_2",
                "executable": True,
                "arguments": {"command": "printf later > note.txt", "cwd": None},
                "timeout_sec": 30,
                "recorded_exit_code": 0,
                "recorded_output": "",
            },
        ],
    )
    # First action matches a failure, so the second still runs. Divergence stops the rest.
    ctx.replay_plan["actions"][0]["recorded_exit_code"] = 0
    from ageval.attempt.replay_exec import execute_recorded_actions

    asyncio.run(execute_recorded_actions(ctx))
    assert ctx.replay_provenance["status"] == "diverged"
    assert ctx.replay_provenance["actions_executed"] == 1
    note = ctx.host.host_path(f"{WORKSPACE_PATH}/note.txt")
    assert note.read_text(encoding="utf-8") == "hello\n"
