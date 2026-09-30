"""Timeout keeps in-flight ACP rows so parent seal can fold them into trajectory."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.helpers.box import local_box

from ageval.environments.protocol import Placement
from ageval.plugins.contrib.acp import build_acp_executor
from ageval.plugins.contrib.acp.client import _AgevalAcpClient
from ageval.plugins.contrib.acp.executor import AcpExecutor
from ageval.plugins.errors import ExtensionMaterializeError

_TOOL = {
    "type": "session_update",
    "session_id": "s1",
    "update": {
        "sessionUpdate": "tool_call",
        "toolCallId": "c1",
        "title": "python variants.py",
        "kind": "execute",
    },
}


def _executor(**kwargs: object) -> AcpExecutor:
    return AcpExecutor(
        host=local_box("/nowhere"),
        placement=Placement(target_id="unstarted", home="/attempt/home"),
        entry_id="pi",
        model="entry-default",
        **kwargs,  # type: ignore[arg-type]
    )


def _timeout_run(
    ex: AcpExecutor, client: _AgevalAcpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setattr(ex, "_ensure_session", lambda **_k: None)
    n = {"i": 0}

    def fake_run(coro: object, timeout: float = 0) -> object:
        del timeout
        getattr(coro, "close", lambda: None)()
        n["i"] += 1
        if n["i"] == 1:
            client.record(dict(_TOOL))
        raise TimeoutError

    monkeypatch.setattr(ex, "_run", fake_run)


def test_timeout_returns_mapped_tool_events(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _executor()
    client = _AgevalAcpClient()
    ex._client = client
    _timeout_run(ex, client, monkeypatch)
    result = ex.invoke("hi", timeout=1)
    assert result.ok is False
    assert result.error == "acp_timeout"
    assert result.repeatable is False
    assert any(ev.get("kind") == "tool" for ev in result.events)
    assert any(ev.get("phase") == "timeout" for ev in result.events)


def test_timeout_writes_vendor_jsonl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ex = _executor()
    client = _AgevalAcpClient()
    ex._client = client
    _timeout_run(ex, client, monkeypatch)
    result = ex.invoke("hi", timeout=1, collect_dir=str(tmp_path))
    assert result.error == "acp_timeout"
    assert any(ev.get("kind") == "tool" for ev in result.events)
    vendor = (tmp_path / "acp_events.jsonl").read_text(encoding="utf-8")
    assert "tool_call" in vendor
    assert "c1" in vendor


class _HangConn:
    def __init__(self, hang_s: float = 30.0, *, updates: int = 0, gap_s: float = 0.05) -> None:
        self.hang_s = hang_s
        self.updates = updates
        self.gap_s = gap_s
        self.cancelled = 0
        self.client: _AgevalAcpClient | None = None

    async def prompt(self, **kwargs: object) -> SimpleNamespace:
        del kwargs
        for _ in range(self.updates):
            if self.client is not None:
                await self.client.session_update("s1", SimpleNamespace())
            await asyncio.sleep(self.gap_s)
        await asyncio.sleep(self.hang_s)
        return SimpleNamespace(stop_reason="end_turn", usage=None)

    async def cancel(self, **kwargs: object) -> None:
        del kwargs
        self.cancelled += 1


def _armed(ex: AcpExecutor, conn: _HangConn, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _AgevalAcpClient()
    ex._client = client
    ex._acp_session_id = "s1"
    conn.client = client
    ex._conn = conn
    monkeypatch.setattr(ex, "_ensure_session", lambda **_k: None)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)


def test_idle_timeout_ends_a_silent_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _executor(idle_timeout_seconds=0.2)
    conn = _HangConn(hang_s=30.0)
    _armed(ex, conn, monkeypatch)
    started = time.monotonic()
    result = ex.invoke("hi", timeout=5)
    elapsed = time.monotonic() - started
    assert result.ok is False
    assert result.error == "acp_idle_timeout"
    assert result.repeatable is True
    assert elapsed < 2.0
    assert conn.cancelled >= 1
    assert any(
        ev.get("phase") == "timeout" and ev.get("reason") == "acp_idle_timeout"
        for ev in result.events
    )
    assert result.metadata is not None
    assert result.metadata.get("idle_timeout_seconds") == 0.2


def test_idle_timeout_resets_when_session_updates_keep_coming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ex = _executor(idle_timeout_seconds=0.25)
    conn = _HangConn(hang_s=0.0, updates=6, gap_s=0.08)
    _armed(ex, conn, monkeypatch)
    result = ex.invoke("hi", timeout=5)
    assert result.ok is True
    assert result.error is None
    assert conn.cancelled == 0


def test_wall_timeout_still_caps_a_longer_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _executor(idle_timeout_seconds=10.0)
    conn = _HangConn(hang_s=30.0)
    _armed(ex, conn, monkeypatch)
    started = time.monotonic()
    result = ex.invoke("hi", timeout=0.3)
    elapsed = time.monotonic() - started
    assert result.error == "acp_timeout"
    assert elapsed < 2.0


def test_factory_reads_idle_timeout_seconds() -> None:
    ex = build_acp_executor(
        options={"entry": "pi", "idle_timeout_seconds": 8},
        host=local_box("/nowhere"),
        placement=Placement(target_id="unstarted", home="/attempt/home"),
    )
    assert ex.idle_timeout_seconds == 8.0
    unset = build_acp_executor(
        options={"entry": "pi", "idle_timeout_seconds": 0},
        host=local_box("/nowhere"),
        placement=Placement(target_id="unstarted", home="/attempt/home"),
    )
    assert unset.idle_timeout_seconds is None


def test_factory_rejects_non_numeric_idle_timeout() -> None:
    with pytest.raises(ExtensionMaterializeError, match="acp_idle_timeout_invalid"):
        build_acp_executor(
            options={"entry": "pi", "idle_timeout_seconds": "soon"},
            host=local_box("/nowhere"),
            placement=Placement(target_id="unstarted", home="/attempt/home"),
        )
