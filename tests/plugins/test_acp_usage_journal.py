"""Session-journal usage fills an ACP result that received none."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.helpers.box import local_box

from ageval.environments.protocol import Placement
from ageval.plugins.agent_result import AgentResult
from ageval.plugins.contrib.acp.client import _AgevalAcpClient
from ageval.plugins.contrib.acp.executor import AcpExecutor
from ageval.plugins.contrib.acp.registry import get_entry
from ageval.plugins.contrib.acp.usage_journal import sum_journal_text

_ASSISTANT = {
    "type": "message",
    "message": {
        "role": "assistant",
        "usage": {
            "input": 10,
            "output": 4,
            "cacheRead": 100,
            "cacheWrite": 7,
            "reasoning": 2,
            "totalTokens": 121,
            "cost": {
                "input": 0.01,
                "output": 0.02,
                "cacheRead": 0.0,
                "cacheWrite": 0.0,
                "total": 0.03,
            },
        },
    },
}
_SECOND = {
    "type": "message",
    "message": {
        "role": "assistant",
        "usage": {
            "input": 3,
            "output": 1,
            "cacheRead": 5,
            "cacheWrite": 0,
            "totalTokens": 9,
            "cost": {"total": 0.01},
        },
    },
}


def _write_session(root: Path) -> None:
    session = root / "home" / ".pi" / "agent" / "sessions" / "2026-10-16" / "one.jsonl"
    session.parent.mkdir(parents=True)
    lines = [
        {"type": "session", "version": 3, "id": "s"},
        {"type": "message", "message": {"role": "user", "content": "hi"}},
        _ASSISTANT,
        _SECOND,
        {
            "type": "usage",
            "usage": {
                "input": 1,
                "output": 0,
                "cacheRead": 0,
                "totalTokens": 1,
                "cost": {"total": 0.0},
            },
        },
        {"type": "compaction", "summary": "no usage on this one"},
        "{not json",
    ]
    session.write_text(
        "\n".join(json.dumps(line) if not isinstance(line, str) else line for line in lines) + "\n",
        encoding="utf-8",
    )


def _executor(root: Path) -> AcpExecutor:
    return AcpExecutor(
        host=local_box(root),
        placement=Placement(target_id="local", home="/attempt/home"),
        entry_id="pi",
        model="entry-default",
    )


def test_sum_ignores_user_rows_and_bad_lines() -> None:
    desc = get_entry("pi")
    assert desc is not None
    journal = desc.usage_journal
    assert journal is not None
    text = "\n".join(
        [
            json.dumps({"type": "message", "message": {"role": "user", "usage": {"input": 99}}}),
            json.dumps(_ASSISTANT),
            "{",
            json.dumps(
                {
                    "type": "compaction",
                    "usage": {
                        "input": 2,
                        "output": 1,
                        "cacheRead": 0,
                        "totalTokens": 3,
                        "cost": {"total": 0.005},
                    },
                }
            ),
        ]
    )
    usage, extra = sum_journal_text(text, journal)
    assert usage is not None and extra is not None
    assert usage["prompt_tokens"] == 12
    assert usage["completion_tokens"] == 5
    assert usage["cached_tokens"] == 100
    assert usage["cost_usd"] == pytest.approx(0.035)
    assert extra["cached_write_tokens"] == 7
    assert extra["reasoning_tokens"] == 2
    assert extra["total_tokens"] == 124
    assert extra["sources"]["session_journal"] is True


def test_timeout_uses_session_journal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_session(tmp_path)
    ex = _executor(tmp_path)
    client = _AgevalAcpClient()
    ex._client = client
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setattr(ex, "_ensure_session", lambda **_k: None)

    def fake_run(coro: object, timeout: float = 0) -> object:
        del timeout
        getattr(coro, "close", lambda: None)()
        raise TimeoutError

    monkeypatch.setattr(ex, "_run", fake_run)
    result = ex.invoke("hi", timeout=1)
    assert result.ok is False
    assert result.error == "acp_timeout"
    assert result.usage is not None
    assert result.usage["prompt_tokens"] == 14
    assert result.usage["completion_tokens"] == 5
    assert result.usage["cached_tokens"] == 105
    assert result.usage["cost_usd"] == pytest.approx(0.04)
    assert result.extra is not None
    assert result.extra["usage_partial"] is True
    assert result.extra["usage_source"] == "session_journal"
    assert result.extra["total_tokens"] == 131


def test_finished_prompt_journal_is_not_partial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_session(tmp_path)
    ex = _executor(tmp_path)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setattr(ex, "_ensure_session", lambda **_k: None)

    def fake_run(coro: object, timeout: float = 0) -> AgentResult:
        del timeout
        getattr(coro, "close", lambda: None)()
        return AgentResult(model="m", text="done", structured=None, ok=True)

    monkeypatch.setattr(ex, "_run", fake_run)
    result = ex.invoke("hi", timeout=1)
    assert result.ok is True
    assert result.usage is not None
    assert result.usage["prompt_tokens"] == 14
    assert result.extra is not None
    assert "usage_partial" not in result.extra
    assert "usage_source" not in result.extra
    assert result.extra["sources"]["session_journal"] is True


def test_protocol_error_uses_session_journal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_session(tmp_path)
    ex = _executor(tmp_path)
    ex._client = _AgevalAcpClient()
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setattr(ex, "_ensure_session", lambda **_k: None)

    def fake_run(coro: object, timeout: float = 0) -> object:
        del timeout
        getattr(coro, "close", lambda: None)()
        raise RuntimeError("pipe closed")

    monkeypatch.setattr(ex, "_run", fake_run)
    result = ex.invoke("hi", timeout=1)
    assert result.ok is False
    assert result.error == "acp_protocol_error"
    assert result.usage is not None
    assert result.usage["prompt_tokens"] == 14
    assert result.extra is not None
    assert result.extra["usage_partial"] is True
    assert result.extra["usage_source"] == "session_journal"


def test_journal_keeps_acp_source_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_session(tmp_path)
    ex = _executor(tmp_path)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setattr(ex, "_ensure_session", lambda **_k: None)

    def fake_run(coro: object, timeout: float = 0) -> AgentResult:
        del timeout
        getattr(coro, "close", lambda: None)()
        return AgentResult(
            model="m",
            text="done",
            structured=None,
            ok=True,
            extra={
                "sources": {"prompt_usage": True, "usage_update": False},
                "context": {"used": 9},
            },
        )

    monkeypatch.setattr(ex, "_run", fake_run)
    result = ex.invoke("hi", timeout=1)
    assert result.usage is not None
    assert result.usage["prompt_tokens"] == 14
    assert result.extra is not None
    assert result.extra["sources"]["prompt_usage"] is True
    assert result.extra["sources"]["session_journal"] is True
    assert result.extra["context"] == {"used": 9}
    assert "usage_partial" not in result.extra


def test_existing_acp_usage_skips_journal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_session(tmp_path)
    ex = _executor(tmp_path)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setattr(ex, "_ensure_session", lambda **_k: None)

    def fake_run(coro: object, timeout: float = 0) -> AgentResult:
        del timeout
        getattr(coro, "close", lambda: None)()
        return AgentResult(
            model="m",
            text="done",
            structured=None,
            ok=True,
            usage={"prompt_tokens": 3, "completion_tokens": 1},
            extra={"sources": {"prompt_usage": True, "usage_update": False}},
        )

    monkeypatch.setattr(ex, "_run", fake_run)
    result = ex.invoke("hi", timeout=1)
    assert result.usage == {"prompt_tokens": 3, "completion_tokens": 1}
    assert result.extra is not None
    assert "session_journal" not in result.extra.get("sources", {})
