"""ACP updates and worker step lines reach the activity log while the call is open."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from tests.helpers.box import local_box

from ageval.environments.protocol import ExecResult, ProbeStatus
from ageval.evidence.activity import ActivityLog, ActivityScope
from ageval.plugins.contrib.acp.activity_stream import (
    apply_update,
    note_native_session,
    prime_stream_state,
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
        path = host.state_root / "steps.jsonl"
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


def test_exec_with_steps_keeps_the_worker_busy(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    host = local_box(tmp_path / "box")
    asyncio.run(host.start())

    async def run() -> tuple[ExecResult, ProbeStatus, dict[str, object]]:
        task = asyncio.create_task(
            exec_with_steps(
                host,
                ["python3", "-c", "import time; time.sleep(2)"],
                scope,
            )
        )
        deadline = time.monotonic() + 5
        busy = False
        while time.monotonic() < deadline:
            seen = await host.probe({})
            if seen.status == "busy" and seen.inflight_request_id == "req":
                busy = True
                break
            await asyncio.sleep(0.05)
        assert busy
        result = await task
        idle = await host.probe({})
        last = json.loads((host.state_root / "last_exit.json").read_text(encoding="utf-8"))
        return result, idle, last

    try:
        result, idle, last = asyncio.run(run())
    finally:
        asyncio.run(host.stop(delete=True))
    assert result.exit_code == 0
    assert idle.status == "idle"
    assert last["request_id"] == "req"
    assert scope.log.matches_inflight_tool("req") is False


def test_load_replay_does_not_append_completed_history(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    note_native_session(scope, "native-1")
    scope.record_model_turn_in_flight(1, [])
    scope.record_model_turn_completed(1, assistant_text="wrote the file")
    scope.record_tool_call_in_flight("call_9", "bash", "execute", {"command": "ls"})
    scope.record_tool_call_completed("call_9", outcome="ok", exit_code=0, content="listed")
    before = len(scope.log.records)
    client = _AgevalAcpClient()
    client.activity = scope

    class Conn:
        async def load_session(self, **kwargs: object) -> SimpleNamespace:
            del kwargs
            await client.session_update(
                "native-1",
                _Tool("tool_call", "completed"),
            )
            return SimpleNamespace(session_id="native-1")

        async def new_session(self, **kwargs: object) -> SimpleNamespace:
            del kwargs
            return SimpleNamespace(session_id="fresh")

    executor = AcpExecutor.__new__(AcpExecutor)
    executor._conn = Conn()
    executor._client = client
    executor.activity = scope
    opened, resumed = asyncio.run(executor._open_acp_session("/attempt/workspace"))
    assert resumed is True
    assert opened.session_id == "native-1"
    assert len(scope.log.records) == before
    assert client.suppress_activity is False
    state = prime_stream_state(client, scope)
    assert state.step == 1
    assert "call_9" in state.finished
    apply_update(
        scope,
        client,
        SimpleNamespace(session_update="agent_message_chunk"),
        {"text": "next", "update": {"sessionUpdate": "agent_message_chunk"}},
    )
    steps = [
        record.payload.get("step_index")
        for record in scope.log.records
        if record.kind == "model_turn" and record.status == "in_flight"
    ]
    assert steps == [1, 2]


def test_remote_step_log_is_pulled_without_a_bind_mount(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    line = json.dumps(
        {
            "type": "tool_call",
            "tool_call_id": "bash_1",
            "name": "bash",
            "tool_kind": "execute",
            "arguments": {"command": "ls"},
        }
    )

    class Host:
        async def exec(self, command: list[str], **kwargs: object) -> ExecResult:
            del command, kwargs
            await asyncio.sleep(0.05)
            return ExecResult(exit_code=0)

        async def download(self, source: str, dest: Path, service: str | None = None) -> None:
            del source, service
            Path(dest).write_text(line + "\n", encoding="utf-8")

    result = asyncio.run(exec_with_steps(Host(), ["ignored"], scope))
    assert result.exit_code == 0
    assert any(
        record.kind == "tool_call" and record.payload.get("tool_call_id") == "bash_1"
        for record in scope.log.records
    )


def test_box_executors_forward_activity_to_the_worker() -> None:
    import sys

    root = Path(__file__).resolve().parents[2]
    for rel in (
        "plugins/openhands/src",
        "plugins/acp-oneshot/src",
        "plugins/dsh/src",
        "plugins/nooa/src",
    ):
        path = str(root / rel)
        if path not in sys.path:
            sys.path.insert(0, path)
    from acp_oneshot_plugin.factory import AcpOneshotExecutorSPI
    from dsh_plugin.factory import DshExecutorSPI
    from nooa_plugin.factory import NooaExecutorSPI
    from openhands_plugin.factory import OpenHandsExecutorSPI

    scope = object()
    for cls in (OpenHandsExecutorSPI, AcpOneshotExecutorSPI, DshExecutorSPI, NooaExecutorSPI):
        spi = cast(Any, cls.__new__(cls))
        spi._box = SimpleNamespace(activity=None)
        cast(Any, cls.bind_activity)(spi, scope)
        assert spi.activity is scope
        assert spi._box.activity is scope


def test_worker_step_log_follows_ageval_state_dir(monkeypatch, tmp_path: Path) -> None:
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    scripts = (
        root / "plugins/openhands/worker/ageval_executor_openhands.py",
        root / "plugins/acp-oneshot/worker/ageval_acp_oneshot.py",
        root / "plugins/dsh/worker/ageval_executor_dsh.py",
        root / "plugins/nooa/src/nooa_plugin/trajectory.py",
    )
    monkeypatch.setenv("AGEVAL_STATE_DIR", str(tmp_path / "state"))
    for script in scripts:
        spec = importlib.util.spec_from_file_location(script.stem, script)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module._step_log() == tmp_path / "state" / "steps.jsonl"
    monkeypatch.delenv("AGEVAL_STATE_DIR")
    spec = importlib.util.spec_from_file_location("oneshot_again", scripts[1])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._step_log() == Path("/tmp/.ageval-state/steps.jsonl")


def test_box_result_keeps_activity_steps_the_worker_omitted(tmp_path: Path) -> None:
    import sys

    root = Path(__file__).resolve().parents[2]
    for rel in ("plugins/acp-oneshot/src", "plugins/dsh/src", "plugins/nooa/src"):
        path = str(root / rel)
        if path not in sys.path:
            sys.path.insert(0, path)
    from acp_oneshot_plugin.container import AcpOneshotBoxExecutor
    from dsh_plugin.container import DshBoxExecutor
    from nooa_plugin.container import NooaBoxExecutor

    scope = _scope(tmp_path)
    scope.record_tool_call_in_flight("old_tool", "bash", "execute", {"command": "ls"})
    scope.record_tool_call_completed("old_tool", outcome="ok", exit_code=0, content="listed")
    scope.record_tool_call_in_flight("new_tool", "bash", "execute", {"command": "cat"})
    scope.record_tool_call_completed("new_tool", outcome="ok", exit_code=0, content="file")
    fresh = {
        "schema": "ageval.trajectory.event/1",
        "kind": "tool",
        "phase": "update",
        "tool_call_id": "new_tool",
    }
    payload = {"ok": True, "text": "done", "events": [fresh], "model": "m"}

    oneshot = cast(Any, AcpOneshotBoxExecutor.__new__(AcpOneshotBoxExecutor))
    oneshot.activity = scope
    oneshot.model = "m"
    oneshot.entry_id = "pi"
    oneshot.reasoning_effort = None
    oneshot_ids = [
        event.get("tool_call_id")
        for event in oneshot._result_from(
            SimpleNamespace(stdout="", stderr="", exit_code=0),
            collect_dir=None,
            payload=payload,
        ).events
        if event.get("kind") == "tool"
    ]
    assert oneshot_ids == ["old_tool", "old_tool", "new_tool"]

    stdout = json.dumps(payload)
    for cls, extra in (
        (DshBoxExecutor, {"composition": "slim", "permission": None}),
        (NooaBoxExecutor, {"agent_ref": "agent"}),
    ):
        box = cast(Any, cls.__new__(cls))
        box.activity = scope
        box.model = "m"
        for key, value in extra.items():
            setattr(box, key, value)
        ids = [
            event.get("tool_call_id")
            for event in box._result_from(
                SimpleNamespace(stdout=stdout, stderr="", exit_code=0),
                collect_dir=None,
            ).events
            if event.get("kind") == "tool"
        ]
        assert ids == ["old_tool", "old_tool", "new_tool"]


def test_prior_activity_events_keep_steps_missing_from_the_fresh_stream(tmp_path: Path) -> None:
    from ageval.plugins.activity_events import prior_activity_events

    scope = _scope(tmp_path)
    scope.record_model_turn_in_flight(1, [])
    scope.record_model_turn_completed(1, assistant_text="first thought about the tree")
    scope.record_tool_call_in_flight("old_tool", "bash", "execute", {"command": "ls"})
    scope.record_tool_call_completed("old_tool", outcome="ok", exit_code=0, content="listed")
    scope.record_model_turn_in_flight(2, [])
    scope.record_model_turn_completed(2, assistant_text="after resume the agent continues")
    scope.record_tool_call_in_flight("new_tool", "bash", "execute", {"command": "cat"})
    scope.record_tool_call_completed("new_tool", outcome="ok", exit_code=0, content="file")
    fresh = (
        {
            "schema": "ageval.trajectory.event/1",
            "kind": "text",
            "channel": "assistant",
            "text": "after resume the agent continues",
        },
        {
            "schema": "ageval.trajectory.event/1",
            "kind": "tool",
            "phase": "update",
            "tool_call_id": "new_tool",
        },
    )
    merged = prior_activity_events(scope, fresh)
    ids = [event.get("tool_call_id") for event in merged if event.get("kind") == "tool"]
    assert ids == ["old_tool", "old_tool", "new_tool"]
    assert any(event.get("text") == "first thought about the tree" for event in merged)
    assert [event.get("text") for event in merged].count("after resume the agent continues") == 1


def test_prior_activity_events_keep_tools_that_follow_their_model_turn(tmp_path: Path) -> None:
    from ageval.plugins.activity_events import prior_activity_events

    scope = _scope(tmp_path)
    scope.record_model_turn_in_flight(1, [])
    scope.record_model_turn_completed(1, assistant_text="plan the first commands")
    scope.record_tool_call_in_flight("exec-before", "bash", "execute", {"command": "ls"})
    scope.record_tool_call_completed("exec-before", outcome="ok", exit_code=0, content="listed")
    scope.record_tool_call_in_flight("exec-after", "bash", "execute", {"command": "cat"})
    scope.record_tool_call_completed("exec-after", outcome="ok", exit_code=0, content="file")
    fresh = (
        {
            "schema": "ageval.trajectory.event/1",
            "kind": "tool",
            "phase": "start",
            "tool_call_id": "exec-after",
        },
    )
    merged = prior_activity_events(scope, fresh)
    ids = [event.get("tool_call_id") for event in merged if event.get("kind") == "tool"]
    assert ids == ["exec-before", "exec-before", "exec-after"]
    assert any(event.get("text") == "plan the first commands" for event in merged)


def test_prior_activity_events_fill_tools_the_fresh_stream_skipped(tmp_path: Path) -> None:
    from ageval.plugins.activity_events import prior_activity_events

    scope = _scope(tmp_path)
    for call_id in ("keep", "gap", "again"):
        scope.record_tool_call_in_flight(call_id, "bash", "execute", {"command": call_id})
        scope.record_tool_call_completed(call_id, outcome="ok", exit_code=0, content=call_id)
    fresh = (
        {
            "schema": "ageval.trajectory.event/1",
            "kind": "tool",
            "phase": "update",
            "source": "openhands",
            "tool_call_id": "keep",
        },
        {
            "schema": "ageval.trajectory.event/1",
            "kind": "tool",
            "phase": "update",
            "source": "openhands",
            "tool_call_id": "again",
        },
    )
    merged = prior_activity_events(scope, fresh)
    ids = [event.get("tool_call_id") for event in merged if event.get("kind") == "tool"]
    assert ids == ["keep", "gap", "gap", "again"]
    gap = [event for event in merged if event.get("tool_call_id") == "gap"]
    assert gap[0]["source"] == "activity"


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
