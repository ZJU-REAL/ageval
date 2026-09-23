"""Eval worker parent serve loop: drain stderr while waiting for frames."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.environments.protocol import ExecResult
from ageval.runtime.task_launch import (
    _STDERR_TAIL_BYTES,
    _handle_eval_exec,
    _serve_eval_worker,
)

_FLOOD_SCRIPT = r"""
import json, struct, sys
sys.stderr.write("x" * 80000)
sys.stderr.flush()
raw = json.dumps({"ok": True, "verdict": {"status": "PASS", "score": 1.0}}).encode()
sys.stdout.buffer.write(struct.pack("!I", len(raw)) + raw)
sys.stdout.buffer.flush()
sys.stdin.read()
"""


@pytest.mark.asyncio
async def test_serve_eval_worker_drains_stderr_before_verdict() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _FLOOD_SCRIPT,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    ctx = SimpleNamespace()
    envelope = await asyncio.wait_for(_serve_eval_worker(process, ctx, timeout=5.0), timeout=6.0)
    assert envelope.get("ok") is True
    assert envelope.get("verdict") == {"status": "PASS", "score": 1.0}
    stderr = str(envelope.get("stderr") or "")
    assert stderr.endswith("x" * min(80000, _STDERR_TAIL_BYTES))
    assert len(stderr) <= _STDERR_TAIL_BYTES


class _TimeoutHost:
    def __init__(self) -> None:
        self.kind = "docker"
        self.timeouts: list[float | None] = []
        self.started = False

    async def preflight(self) -> None:
        return None

    async def start(self, *, force_build: bool = False) -> None:
        del force_build
        self.started = True

    async def upload(self, source: Path, dest: str) -> None:
        del source, dest

    async def exec(self, command: list[str], **kwargs: object) -> ExecResult:
        del command
        raw = kwargs.get("timeout_sec")
        self.timeouts.append(float(raw) if isinstance(raw, int | float) else None)
        return ExecResult(exit_code=0, stdout="ok\n")


def _exec_ctx(host: _TimeoutHost, remaining: float | None) -> SimpleNamespace:
    return SimpleNamespace(
        remaining_seconds=lambda: remaining,
        lock=SimpleNamespace(
            force_build=False,
            resolved_references={
                "evaluation_environments": {
                    "audit": {"dockerfile": "environment/evaluate/audit/Dockerfile"}
                },
                "artifacts": [],
                "evaluation_inputs": [],
            },
        ),
        evaluate_hosts={"audit": host},
        started_evaluate_names={"audit"},
        record_fact=lambda *_a, **_k: None,
        evaluation_src=None,
        evidence=None,
    )


@pytest.mark.asyncio
async def test_handle_eval_exec_clamps_timeout_to_remaining_wall() -> None:
    host = _TimeoutHost()
    reply = await _handle_eval_exec(
        _exec_ctx(host, 3.5),
        {"id": "1", "environment": "audit", "argv": ["echo", "ok"], "timeout_sec": 30},
    )
    assert reply.get("error") is None
    assert host.timeouts == [3.5]


@pytest.mark.asyncio
async def test_handle_eval_exec_keeps_caller_timeout_inside_the_wall() -> None:
    host = _TimeoutHost()
    await _handle_eval_exec(
        _exec_ctx(host, 10.0),
        {"id": "1", "environment": "audit", "argv": ["echo", "ok"], "timeout_sec": 1.25},
    )
    assert host.timeouts == [1.25]


@pytest.mark.asyncio
async def test_handle_eval_exec_uses_remaining_when_caller_omits_timeout() -> None:
    host = _TimeoutHost()
    await _handle_eval_exec(
        _exec_ctx(host, 4.0),
        {"id": "1", "environment": "audit", "argv": ["echo", "ok"]},
    )
    assert host.timeouts == [4.0]


@pytest.mark.asyncio
async def test_handle_eval_exec_expired_wall_does_not_start_or_exec() -> None:
    host = _TimeoutHost()
    reply = await _handle_eval_exec(
        _exec_ctx(host, 0.0),
        {"id": "1", "environment": "audit", "argv": ["sleep", "inf"]},
    )
    assert reply.get("error") == "evaluate_timeout"
    assert host.timeouts == []
    assert host.started is False
