"""Completed miniswe and terminus steps are not sent again."""

from __future__ import annotations

import sys
from pathlib import Path

from tests.helpers.box import local_box

from ageval.environments.protocol import ExecResult
from ageval.evidence.activity import ActivityLog, ActivityScope

ROOT = Path(__file__).resolve().parents[2]
for rel in ("plugins/miniswe/src", "plugins/terminus-2/src"):
    path = str(ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)

from miniswe_plugin.activity_replay import install_activity  # noqa: E402
from terminus2_plugin.episode import run_episode  # noqa: E402
from terminus2_plugin.tmux import TmuxSession  # noqa: E402


class _Host:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    async def exec(self, command, **kwargs):
        del kwargs
        script = str(command[-1]) if command else ""
        self.scripts.append(script)
        if "capture-pane" in script or "has-session" in script or script.strip() == "tmux -V":
            return ExecResult(exit_code=0, stdout="$ \n")
        return ExecResult(exit_code=0)


def _session(host: _Host) -> TmuxSession:
    return TmuxSession(
        host,
        session_name="t2replay",
        cwd="/attempt/workspace",
        user=None,
        pane_width=80,
        pane_height=24,
        cmd_timeout=5,
    )


class _Model:
    def __init__(self) -> None:
        self.calls = 0

    def query(self, messages, **kwargs):
        del messages, kwargs
        self.calls += 1
        return {
            "role": "assistant",
            "content": "done",
            "extra": {"actions": [{"command": "echo hi"}], "cost": 0.1},
        }


class _Env:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.timeout = 5

    def execute(self, action, cwd="", *, timeout=None):
        del cwd, timeout
        self.calls.append(str(action.get("command") or ""))
        return {"output": "hi\n", "returncode": 0, "exception_info": ""}


def test_miniswe_replay_skips_completed_query_and_bash(tmp_path: Path) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="sess", invoke_request_id="req")
    model = _Model()
    env = _Env()
    executor = type("Ex", (), {"activity": scope})()
    install_activity(model, env, executor)
    first = model.query([{"role": "user", "content": "go"}])
    env.execute(first["extra"]["actions"][0])
    assert model.calls == 1
    assert env.calls == ["echo hi"]

    again_model = _Model()
    again_env = _Env()
    again = type("Ex", (), {"activity": scope})()
    install_activity(again_model, again_env, again)
    replayed = again_model.query([{"role": "user", "content": "go"}])
    again_env.execute(replayed["extra"]["actions"][0])
    assert again_model.calls == 0
    assert again_env.calls == []
    assert replayed["content"] == "done"
    again_env.execute({"command": "echo next"})
    ids = [
        record.payload.get("tool_call_id")
        for record in scope.log.records
        if record.kind == "tool_call" and record.status == "in_flight"
    ]
    assert ids == ["bash_1", "bash_2"]


def test_miniswe_tail_keeps_every_tool_result() -> None:
    from miniswe_plugin.activity_replay import _tail

    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "two commands"},
        {"role": "tool", "content": "first"},
        {"role": "tool", "content": "second"},
    ]
    assert [item["content"] for item in _tail(messages)] == ["first", "second"]


def test_terminus_restore_does_not_replay_keystrokes(tmp_path: Path) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(
        log, session_id="sess", invoke_request_id="req", environment_reattached=True
    )
    scope.record_model_turn_in_flight(
        1,
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "do it"},
        ],
    )
    scope.record_model_turn_completed(1, assistant_text="analysis")
    scope.record_tool_call_in_flight("tmux_0", "tmux", "execute", {"command": "echo hi\n"})
    scope.record_tool_call_completed(
        "tmux_0",
        outcome="ok",
        exit_code=0,
        content="next user prompt",
        checkpoint_seq=None,
    )
    calls = {"n": 0}

    def model(messages):
        calls["n"] += 1
        assert messages[-1]["content"] == "next user prompt"
        text = '{"analysis":"a","plan":"p","commands":[],"task_complete":true}'
        return type("Reply", (), {"text": text, "usage": {}})()

    host = _Host()
    session = _session(host)
    result = run_episode(
        instruction="do it",
        session=session,
        model=model,
        parser="json",
        step_limit=3,
        max_format_errors=2,
        timeout=10,
        session_id="sess",
        activity=scope,
        reuse_session=False,
    )
    assert result.ok is True
    assert calls["n"] == 1
    assert not any("echo hi" in script for script in host.scripts)


def test_terminus_compaction_drops_replaced_turns(tmp_path: Path) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="sess", invoke_request_id="req")
    scope.record_model_turn_in_flight(1, [{"role": "user", "content": "old"}])
    done = scope.record_model_turn_completed(1, assistant_text="old reply")
    scope.record_compaction(
        source="parent_executor",
        replaces_through_seq=done.seq,
        summary_messages=[{"role": "user", "content": "summary"}],
    )
    seen: list[str] = []

    def model(messages):
        seen.append(str(messages[-1]["content"]))
        text = '{"analysis":"a","plan":"p","commands":[],"task_complete":true}'
        return type("Reply", (), {"text": text, "usage": {}})()

    host = _Host()
    result = run_episode(
        instruction="do it",
        session=_session(host),
        model=model,
        parser="json",
        step_limit=2,
        max_format_errors=1,
        timeout=10,
        session_id="sess",
        activity=scope,
        reuse_session=False,
    )
    assert result.ok is True
    assert seen == ["summary"]
    assert "old reply" not in seen


def test_terminus_format_error_survives_resume(tmp_path: Path) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="sess", invoke_request_id="req")

    def bad(messages):
        del messages
        return type("Reply", (), {"text": "not-json", "usage": {}})()

    first = run_episode(
        instruction="do it",
        session=_session(_Host()),
        model=bad,
        parser="json",
        step_limit=1,
        max_format_errors=3,
        timeout=10,
        session_id="sess",
        activity=scope,
        reuse_session=False,
    )
    assert first.error == "terminus2_step_limit"
    reasons = [
        record.payload.get("stop_reason")
        for record in scope.log.records
        if record.kind == "model_turn" and record.status == "completed"
    ]
    assert reasons == ["format_error"]

    calls = {"n": 0}

    def again(messages):
        calls["n"] += 1
        assert "Could not parse" in str(messages[-1]["content"])
        return type("Reply", (), {"text": "still-bad", "usage": {}})()

    second = run_episode(
        instruction="do it",
        session=_session(_Host()),
        model=again,
        parser="json",
        step_limit=4,
        max_format_errors=2,
        timeout=10,
        session_id="sess",
        activity=scope,
        reuse_session=False,
    )
    assert calls["n"] == 1
    assert second.error is not None
    assert second.error.startswith("terminus2_format:")


def test_terminus_reuses_live_tmux_session() -> None:
    host = _Host()
    session = _session(host)
    session.start(reuse=True)
    assert not any("new-session" in script for script in host.scripts)


def test_local_exec_records_last_exit(tmp_path: Path) -> None:
    import asyncio

    host = local_box(tmp_path / "box")
    asyncio.run(host.start())
    result = asyncio.run(host.exec(["/bin/echo", "hi"], request_id="call_1"))
    assert result.exit_code == 0
    probe = asyncio.run(host.probe({}))
    assert probe.status == "idle"
    assert probe.last_exit is not None
    assert probe.last_exit["request_id"] == "call_1"
    assert "hi" in probe.last_exit["stdout"]
