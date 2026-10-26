"""openhands and dsh resume a native session; nooa replays the transcript."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from ageval.evidence.activity import ActivityLog, ActivityScope
from ageval.plugins.contrib.acp.activity_stream import prompt_for_resume

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scope(tmp_path: Path) -> ActivityScope:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="sess", invoke_request_id="req_1")
    scope.record_model_turn_completed(1, assistant_text="wrote the file")
    scope.record_tool_call_in_flight(
        "call_done",
        "execute",
        "execute",
        {"command": "python3 aggregate.py"},
        replay_safe=False,
    )
    scope.record_tool_call_completed(
        "call_done",
        outcome="ok",
        exit_code=0,
        content="rows=3",
    )
    return scope


def test_openhands_resume_opens_the_saved_conversation(tmp_path: Path) -> None:
    worker = _load(
        "oh_worker",
        ROOT / "plugins/openhands/worker/ageval_executor_openhands.py",
    )
    executed: list[str] = []

    class _Conversation:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.id = kwargs.get("conversation_id") or "fresh"
            self.text = ""

        def send_message(self, text: str) -> None:
            self.text = text
            if "python3 aggregate.py" in text:
                executed.append("aggregate.py")

        def run(self) -> None:
            return None

    conversation = worker.start_conversation(
        _Conversation,
        agent=object(),
        workspace=object(),
        persistence_dir="/attempt/home/openhands",
        conversation_id="native-1",
        max_iterations=40,
    )
    conversation.send_message(prompt_for_resume(_scope(tmp_path), "continue", resumed_native=True))
    conversation.run()
    assert conversation.kwargs["persistence_dir"] == "/attempt/home/openhands"
    assert conversation.kwargs["conversation_id"] == "native-1"
    assert conversation.kwargs["delete_on_close"] is False
    assert executed == []


def test_dsh_resume_loads_the_native_session(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("AGEVAL_STATE_DIR", str(tmp_path))
    worker = _load("dsh_worker", ROOT / "plugins/dsh/worker/ageval_executor_dsh.py")
    calls: list[tuple[str, str | None]] = []

    class _Client:
        def request(self, method: str, params: dict[str, str], **kwargs: object) -> None:
            del kwargs
            calls.append((method, params.get("sessionId")))

    class _Harness:
        def __init__(self) -> None:
            self.client = _Client()

        def start_session(self, session_id: str | None = None) -> SimpleNamespace:
            calls.append(("start_session", session_id))
            raise AssertionError("start_session")

    class _Session:
        def __init__(self, harness: object, session_id: str) -> None:
            self.harness = harness
            self.id = session_id
            self.prompt = ""

        def run(self, prompt: str, on_notification: object = None) -> SimpleNamespace:
            del on_notification
            self.prompt = prompt
            return SimpleNamespace(session_id=self.id)

    session = worker.open_dsh_session(
        _Harness(),
        "native-1",
        resume=True,
        session_cls=_Session,
    )
    session.run(prompt_for_resume(_scope(tmp_path), "continue", resumed_native=True))
    assert calls == [("session/resume", "native-1")]
    assert "python3 aggregate.py" not in session.prompt

    class _Fresh:
        def start_session(self, session_id: str | None = None) -> SimpleNamespace:
            calls.append(("start_session", session_id))
            return SimpleNamespace(id="generated-1")

    calls.clear()
    worker.open_dsh_session(_Fresh(), None, resume=False)
    assert calls == [("start_session", None)]
    lines = [
        json.loads(line)
        for line in (tmp_path / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert lines[-1] == {"type": "native_session", "id": "generated-1"}


def test_nooa_resume_prompt_replays_the_transcript(tmp_path: Path) -> None:
    prompt = prompt_for_resume(_scope(tmp_path), "continue", resumed_native=False)
    assert "wrote the file" in prompt
    assert "rows=3" in prompt
    assert "Do not repeat" in prompt
    assert "python3 aggregate.py" not in prompt
