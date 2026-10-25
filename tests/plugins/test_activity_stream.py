"""ACP updates and worker step lines reach the activity log while the call is open."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from tests.helpers.box import local_box

from ageval.environments.protocol import ExecResult
from ageval.evidence.activity import ActivityLog, ActivityScope
from ageval.plugins.contrib.acp.activity_stream import (
    apply_update,
    note_native_session,
    prompt_for_resume,
)
from ageval.plugins.contrib.acp.client import _AgevalAcpClient
from ageval.plugins.contrib.acp.executor import AcpExecutor
from ageval.plugins.step_stream import exec_with_steps


def _scope(tmp_path: Path) -> ActivityScope:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    log.append(
        request_id="attempt",
        kind="attempt",
        status="completed",
        payload={
            "run_id": "run",
            "trial_id": "trial",
            "attempt_id": "attempt",
            "task_id": "task",
            "attempt_index": 0,
            "suite_run_id": None,
            "locked_config_digest": "digest",
            "environment_kind": "local",
            "environment_nonce": "nce_1",
            "environment_handle": None,
        },
    )
    log.append(
        request_id="sess",
        kind="session",
        status="completed",
        payload={
            "session_id": "sess",
            "profile_id": "solver",
            "actor_id": None,
            "environment": "main",
            "executor_kind": "acp",
            "native_session_id": None,
        },
    )
    scope = ActivityScope(log, session_id="sess", invoke_request_id="req")
    scope.capture = lambda seq: seq
    return scope


class _Tool:
    def __init__(self, kind: str, status: str) -> None:
        self.session_update = kind
        self.tool_call_id = "call_1"
        self.title = "read"
        self.kind = "read"
        self.status = status

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        del kwargs
        return {
            "sessionUpdate": self.session_update,
            "toolCallId": self.tool_call_id,
            "title": self.title,
            "kind": self.kind,
            "status": self.status,
            "rawInput": {"path": "a"},
            "rawOutput": "contents",
        }


def test_acp_tool_is_logged_before_prompt_returns(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    client = _AgevalAcpClient(activity=scope)
    seen: list[str] = []

    async def prompt() -> str:
        await client.session_update("native", _Tool("tool_call", "pending"))
        assert any(
            record.kind == "tool_call" and record.status == "in_flight"
            for record in scope.log.records
        )
        seen.append("during")
        await client.session_update("native", _Tool("tool_call_update", "completed"))
        return "done"

    assert asyncio.run(prompt()) == "done"
    assert seen == ["during"]
    completed = [
        record
        for record in scope.log.records
        if record.kind == "tool_call" and record.status == "completed"
    ]
    assert completed[-1].payload["checkpoint_seq"] == completed[-1].seq
    inflight = [
        record
        for record in scope.log.records
        if record.kind == "tool_call" and record.status == "in_flight"
    ]
    assert inflight[-1].payload["replay_safe"] is True


def test_resume_loads_native_session_or_rebuilds_the_transcript(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    note_native_session(scope, "native-1")
    scope.record_model_turn_in_flight(1, [])
    scope.record_model_turn_completed(1, assistant_text="wrote the file")
    scope.record_tool_call_in_flight("call_9", "bash", "execute", {"command": "ls"})
    scope.record_tool_call_completed(
        "call_9",
        outcome="interrupted",
        exit_code=None,
        content="partial",
    )

    class Conn:
        def __init__(self) -> None:
            self.mode = "load"

        async def load_session(self, **kwargs: object) -> SimpleNamespace:
            assert kwargs["session_id"] == "native-1"
            if self.mode == "missing":
                raise RuntimeError("unsupported")
            if self.mode == "blank":
                return SimpleNamespace()
            return SimpleNamespace(session_id="native-1")

        async def new_session(self, **kwargs: object) -> SimpleNamespace:
            del kwargs
            return SimpleNamespace(session_id="fresh")

    executor = AcpExecutor.__new__(AcpExecutor)
    executor._conn = Conn()
    executor.activity = scope
    opened, resumed = asyncio.run(executor._open_acp_session("/attempt/workspace"))
    assert resumed is True
    assert opened.session_id == "native-1"
    executor._conn.mode = "blank"
    opened, resumed = asyncio.run(executor._open_acp_session("/attempt/workspace"))
    assert resumed is True
    assert opened.session_id == "native-1"
    executor._conn.mode = "load"
    native_prompt = prompt_for_resume(scope, "continue", resumed_native=True)
    assert "partial" in native_prompt
    assert "wrote the file" not in native_prompt

    executor._conn.mode = "missing"
    opened, resumed = asyncio.run(executor._open_acp_session("/attempt/workspace"))
    assert resumed is False
    assert opened.session_id == "fresh"
    fallback = prompt_for_resume(scope, "continue", resumed_native=False)
    assert "wrote the file" in fallback
    assert "call_9" in fallback


def test_worker_steps_are_logged_before_exec_returns(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    host = local_box(tmp_path / "box")
    asyncio.run(host.start())

    async def exec(command: list[str], **kwargs: object) -> ExecResult:
        del command, kwargs
        path = host.root / ".ageval-state" / "steps.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "type": "tool_call",
                    "tool_call_id": "bash_1",
                    "name": "bash",
                    "tool_kind": "execute",
                    "arguments": {"command": "ls"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        await asyncio.sleep(0.05)
        assert any(
            record.kind == "tool_call" and record.status == "in_flight"
            for record in scope.log.records
        )
        return ExecResult(exit_code=0)

    host.exec = exec  # type: ignore[method-assign]
    result = asyncio.run(exec_with_steps(host, ["ignored"], scope))
    assert result.exit_code == 0


def test_apply_update_records_compaction(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    client = _AgevalAcpClient()
    apply_update(
        scope,
        client,
        SimpleNamespace(session_update="compaction"),
        {
            "update_type": "compaction",
            "update": {"sessionUpdate": "compaction", "path": "/attempt/home/.pi/session.jsonl"},
        },
    )
    rows = [record for record in scope.log.records if record.kind == "compaction"]
    assert rows[-1].payload["source"] == "native_home"
    assert rows[-1].payload["native_journal_rel"] == ".pi/session.jsonl"
