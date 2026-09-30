"""ACP sets repeatable from this prompt's tool events, not from the stop reason."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from tests.helpers.box import local_box

from ageval.environments.protocol import Placement
from ageval.plugins.contrib.acp.client import _AgevalAcpClient
from ageval.plugins.contrib.acp.executor import AcpExecutor

_EXECUTE = {
    "type": "session_update",
    "session_id": "s1",
    "update": {
        "sessionUpdate": "tool_call",
        "toolCallId": "c1",
        "title": "python variants.py",
        "kind": "execute",
    },
}

_READ = {
    "type": "session_update",
    "session_id": "s1",
    "update": {
        "sessionUpdate": "tool_call",
        "toolCallId": "r1",
        "title": "Read file '/a'",
        "kind": "Read",
    },
}

_READ_UPDATE = {
    "type": "session_update",
    "session_id": "s1",
    "update": {
        "sessionUpdate": "tool_call_update",
        "toolCallId": "r1",
        "status": "completed",
    },
}

_UNKNOWN = {
    "type": "session_update",
    "session_id": "s1",
    "update": {
        "sessionUpdate": "tool_call",
        "toolCallId": "u1",
        "title": "something",
    },
}


def _executor() -> AcpExecutor:
    return AcpExecutor(
        host=local_box("/nowhere"),
        placement=Placement(target_id="unstarted", home="/attempt/home"),
        entry_id="pi",
        model="entry-default",
    )


class _StopConn:
    def __init__(self, client: _AgevalAcpClient, events: tuple[dict[str, object], ...]) -> None:
        self.client = client
        self.events = events

    async def prompt(self, **kwargs: object) -> SimpleNamespace:
        del kwargs
        for ev in self.events:
            self.client.record(dict(ev))
        return SimpleNamespace(stop_reason="refusal", usage=None)


def _armed(
    ex: AcpExecutor,
    events: tuple[dict[str, object], ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _AgevalAcpClient()
    ex._client = client
    ex._acp_session_id = "s1"
    ex._conn = _StopConn(client, events)
    monkeypatch.setattr(ex, "_ensure_session", lambda **_k: None)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)


def test_refusal_after_a_read_stays_repeatable(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _executor()
    _armed(ex, (_READ, _READ_UPDATE), monkeypatch)
    result = ex.invoke("hi", timeout=5)
    ex.close()
    assert result.ok is False
    assert result.error == "acp_stop_refusal"
    assert result.repeatable is True


def test_execute_then_refusal_is_not_repeatable(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _executor()
    _armed(ex, (_EXECUTE,), monkeypatch)
    result = ex.invoke("hi", timeout=5)
    ex.close()
    assert result.ok is False
    assert result.repeatable is False


def test_unknown_tool_kind_is_not_repeatable(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _executor()
    _armed(ex, (_UNKNOWN,), monkeypatch)
    result = ex.invoke("hi", timeout=5)
    ex.close()
    assert result.repeatable is False


def test_protocol_error_keeps_a_prior_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _executor()
    client = _AgevalAcpClient()
    ex._client = client
    monkeypatch.setattr(ex, "_ensure_session", lambda **_k: None)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)

    def fake_run(coro: object, timeout: float = 0) -> object:
        del timeout
        getattr(coro, "close", lambda: None)()
        client.record(dict(_EXECUTE))
        raise RuntimeError("pipe broke")

    monkeypatch.setattr(ex, "_run", fake_run)
    result = ex.invoke("hi", timeout=1)
    assert result.error == "acp_protocol_error"
    assert result.repeatable is False
    assert any(
        ev.get("kind") == "tool" and ev.get("tool_kind") == "execute" for ev in result.events
    )


def test_protocol_error_before_a_tool_stays_repeatable(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _executor()
    ex._client = _AgevalAcpClient()
    monkeypatch.setattr(ex, "_ensure_session", lambda **_k: None)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)

    def fake_run(coro: object, timeout: float = 0) -> object:
        del timeout
        getattr(coro, "close", lambda: None)()
        raise RuntimeError("pipe broke")

    monkeypatch.setattr(ex, "_run", fake_run)
    result = ex.invoke("hi", timeout=1)
    assert result.error == "acp_protocol_error"
    assert result.repeatable is True


def test_session_ensure_failure_stays_repeatable(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _executor()
    monkeypatch.setattr(ex, "_ensure_session", lambda **_k: "acp_protocol_error")
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    result = ex.invoke("hi", timeout=1)
    assert result.ok is False
    assert result.error == "acp_protocol_error"
    assert result.repeatable is True
