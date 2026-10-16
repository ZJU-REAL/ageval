"""The SDK session surface: bounded turns, no authority, no invented success."""

from __future__ import annotations

import asyncio

import pytest

from ageval_sdk import Agent, AgentSession


def test_session_rejects_profile_overrides() -> None:
    session = AgentSession(attempt_id="attempt_x", profile_id="p", max_turns=2)

    async def _run() -> None:
        with pytest.raises(ValueError, match="override"):
            await session.invoke("hi", profile_id="other")

    asyncio.run(_run())


def test_session_forwards_tools_without_treating_them_as_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

    async def _fake_call(payload: dict[str, object]) -> dict[str, object]:
        captured.append(payload)
        if payload.get("op") == "open":
            return {"ok": True, "session_id": "sess_test"}
        return {
            "ok": True,
            "text": "",
            "tool_calls": [
                {"id": "call_1", "name": "lookup", "arguments": {"q": "a"}},
            ],
        }

    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setattr("ageval_sdk.agent._parent_call", _fake_call)
    session = AgentSession(attempt_id="attempt_x", profile_id="p", max_turns=2)
    catalog = [{"type": "function", "function": {"name": "lookup"}}]
    history = [{"role": "user", "content": "hi"}]

    answer = asyncio.run(session.invoke("hi", tools=catalog, messages=history))

    assert answer["ok"] is True
    assert answer["tool_calls"] == [
        {"id": "call_1", "name": "lookup", "arguments": {"q": "a"}},
    ]
    invoke = next(item for item in captured if item.get("op") == "invoke")
    assert invoke["tools"] == catalog
    assert invoke["messages"] == history


def test_session_open_forwards_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, object]] = []

    async def _fake_call(payload: dict[str, object]) -> dict[str, object]:
        captured.append(payload)
        if payload.get("op") == "open":
            return {"ok": True, "session_id": "sess_env"}
        return {"ok": True, "text": "ok", "tool_calls": []}

    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setattr("ageval_sdk.agent._parent_call", _fake_call)
    session = AgentSession(
        attempt_id="attempt_x",
        profile_id="judge",
        max_turns=1,
        environment="verification",
    )
    asyncio.run(session.invoke("score this"))
    opened = next(item for item in captured if item.get("op") == "open")
    assert opened["environment"] == "verification"


def test_record_observation_forwards_to_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

    async def _fake_call(payload: dict[str, object]) -> dict[str, object]:
        captured.append(payload)
        if payload.get("op") == "open":
            return {"ok": True, "session_id": "sess_test"}
        if payload.get("op") == "record_observation":
            return {"ok": True, "tool_call_id": payload.get("tool_call_id")}
        return {
            "ok": True,
            "text": "",
            "invocation_id": "inv_1",
            "tool_calls": [
                {"id": "call_1", "name": "lookup", "arguments": {"q": "a"}},
            ],
        }

    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setattr("ageval_sdk.agent._parent_call", _fake_call)
    session = AgentSession(attempt_id="attempt_x", profile_id="p", max_turns=2)
    asyncio.run(session.invoke("hi"))
    observed = asyncio.run(
        session.record_observation(
            "call_1",
            content='{"ok": true}',
            raw_output={"ok": True},
            function_name="lookup",
        )
    )
    assert observed["ok"] is True
    rec = next(item for item in captured if item.get("op") == "record_observation")
    assert rec["session_id"] == "sess_test"
    assert rec["invocation_id"] == "inv_1"
    assert rec["tool_call_id"] == "call_1"
    assert rec["function_name"] == "lookup"
    assert rec["raw_output"] == {"ok": True}


def test_unbound_session_reports_failure_instead_of_answering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGEVAL_AGENT_SERVICE_SOCK", raising=False)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    session = AgentSession(attempt_id="attempt_x", profile_id="p", max_turns=2)

    answer = asyncio.run(session.invoke("one"))

    assert answer["ok"] is False
    assert answer["error"] == "agent_session_unbound"
    assert answer["text"] == ""
    assert answer["structured"] is None


def test_offline_gate_refuses_before_the_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGEVAL_OFFLINE_AGENT", "1")
    session = AgentSession(attempt_id="attempt_x", profile_id="p", max_turns=2)

    answer = asyncio.run(session.invoke("one"))

    assert (answer["ok"], answer["error"]) == (False, "offline_forced")


def test_local_turn_budget_stops_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGEVAL_AGENT_SERVICE_SOCK", raising=False)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    session = AgentSession(attempt_id="attempt_x", profile_id="p", max_turns=1)

    async def _run() -> None:
        await session.invoke("one")
        with pytest.raises(RuntimeError, match="max_turns"):
            await session.invoke("two")

    asyncio.run(_run())


def test_agent_facade_builds_session() -> None:
    session = Agent(attempt_id="attempt_abc").session("solver", max_turns=3)
    assert isinstance(session, AgentSession)
    assert session.profile_id == "solver"
    assert session.provider_session_handle is None
