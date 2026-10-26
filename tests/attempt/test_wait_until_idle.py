"""A busy probe waits for timeout_sec, or until the process exits."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.recover import classify_environment, write_attempt_header
from ageval.environments.protocol import ProbeStatus
from ageval.evidence.activity import ActivityLog
from ageval.evidence.store import AttemptEvidenceStore
from ageval.plugins.protocol import ExtensionGraph
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.services import ServiceTable
from ageval.runtime.cancellation import CancellationSignal


class _Host:
    def __init__(self, state: Path, *, idle_after: float | None) -> None:
        self.state_root = state
        self.reattached = False
        self.idle_after = idle_after
        self.started = time.monotonic()
        self.probes = 0
        self.attaches = 0

    async def probe(self, handle: dict[str, object]) -> ProbeStatus:
        del handle
        self.probes += 1
        if self.idle_after is not None and time.monotonic() - self.started >= self.idle_after:
            return ProbeStatus(status="idle", nonce="nce_test")
        return ProbeStatus(status="busy", nonce="nce_test")

    async def attach(self, handle: dict[str, object]) -> None:
        del handle
        self.attaches += 1


def _ctx(tmp_path: Path, host: _Host, log: ActivityLog) -> AttemptCtx:
    return AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=None,  # type: ignore[arg-type]
        profile_id="solver",
        bindings=ExtensionGraph(profile_id="solver"),
        registry=ExtensionRegistry(),
        services=ServiceTable(),
        host=host,  # type: ignore[arg-type]
        evidence=AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r"),
        cancellation=CancellationSignal(),
        task_root=tmp_path,
        dataset_root=tmp_path,
        activity=log,
    )


def _log(tmp_path: Path, *, timeout_sec: float | None, deadline_utc: str | None) -> ActivityLog:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    write_attempt_header(
        log,
        run_id="r",
        trial_id="t",
        attempt_id="a",
        task_id="task",
        attempt_index=0,
        suite_run_id=None,
        digest="sha256:abc",
        environment_kind="local",
        nonce="nce_test",
    )
    log.append(
        request_id="call_1",
        kind="tool_call",
        status="in_flight",
        payload={
            "session_id": "sess",
            "invoke_request_id": "req_1",
            "tool_call_id": "call_1",
            "tool_name": "execute",
            "tool_kind": "execute",
            "arguments": {"command": "sleep 5"},
            "replay_safe": False,
            "system_effect": False,
            "timeout_sec": timeout_sec,
            "deadline_utc": deadline_utc,
        },
    )
    return log


@pytest.mark.asyncio
async def test_timeout_sec_waits_until_the_pid_exits(tmp_path: Path) -> None:
    host = _Host(tmp_path / "state", idle_after=0.3)
    started = time.monotonic()
    decision = await classify_environment(
        _ctx(tmp_path, host, _log(tmp_path, timeout_sec=1, deadline_utc=None))
    )
    elapsed = time.monotonic() - started
    assert decision == "attached"
    assert host.attaches == 1
    assert 0.2 < elapsed < 0.9


@pytest.mark.asyncio
async def test_timeout_sec_still_busy_does_not_attach(tmp_path: Path) -> None:
    host = _Host(tmp_path / "state", idle_after=None)
    started = time.monotonic()
    decision = await classify_environment(
        _ctx(tmp_path, host, _log(tmp_path, timeout_sec=1, deadline_utc=None))
    )
    elapsed = time.monotonic() - started
    assert decision == "busy"
    assert host.attaches == 0
    assert 0.8 < elapsed < 1.6


@pytest.mark.asyncio
async def test_no_deadline_waits_until_the_probe_goes_idle(tmp_path: Path) -> None:
    host = _Host(tmp_path / "state", idle_after=0.3)
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    write_attempt_header(
        log,
        run_id="r",
        trial_id="t",
        attempt_id="a",
        task_id="task",
        attempt_index=0,
        suite_run_id=None,
        digest="sha256:abc",
        environment_kind="local",
        nonce="nce_test",
    )
    started = time.monotonic()
    decision = await classify_environment(_ctx(tmp_path, host, log))
    elapsed = time.monotonic() - started
    assert decision == "attached"
    assert host.probes > 1
    assert elapsed < 0.9


@pytest.mark.asyncio
async def test_deadline_utc_stops_the_wait(tmp_path: Path) -> None:
    host = _Host(tmp_path / "state", idle_after=None)
    deadline = (datetime.now(UTC) + timedelta(seconds=0.4)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    started = time.monotonic()
    decision = await classify_environment(
        _ctx(tmp_path, host, _log(tmp_path, timeout_sec=30, deadline_utc=deadline))
    )
    elapsed = time.monotonic() - started
    assert decision == "busy"
    assert 0.3 < elapsed < 0.9
