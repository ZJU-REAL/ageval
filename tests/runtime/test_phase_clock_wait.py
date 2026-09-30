"""Task and eval workers re-read the phase clock instead of one captured timeout."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from ageval.runtime.task_launch import _collect, _serve_eval_worker

_SLOW_OK = r"""
import json, struct, time, sys
time.sleep(0.45)
raw = json.dumps({"ok": True, "verdict": {"status": "PASS"}}).encode()
sys.stdout.buffer.write(struct.pack("!I", len(raw)) + raw)
sys.stdout.buffer.flush()
"""

_HANG = r"""
import time
time.sleep(30)
"""


async def _process(script: str) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


@pytest.mark.asyncio
async def test_collect_keeps_the_worker_when_live_remaining_outlasts_the_capture() -> None:
    process = await _process(_SLOW_OK)
    ctx = SimpleNamespace(remaining_seconds=lambda: 5.0)
    envelope = await asyncio.wait_for(_collect(process, timeout=0.1, ctx=ctx), timeout=2.0)
    assert envelope.get("ok") is True


@pytest.mark.asyncio
async def test_collect_stops_when_live_remaining_hits_zero() -> None:
    process = await _process(_HANG)
    state = {"left": 5.0}

    async def _drop() -> None:
        await asyncio.sleep(0.2)
        state["left"] = 0.0

    drop = asyncio.create_task(_drop())
    ctx = SimpleNamespace(remaining_seconds=lambda: state["left"])
    envelope = await asyncio.wait_for(_collect(process, timeout=30.0, ctx=ctx), timeout=2.0)
    await drop
    assert envelope.get("error") == "task_run_timeout"


@pytest.mark.asyncio
async def test_collect_falls_back_to_the_captured_timeout() -> None:
    process = await _process(_HANG)
    envelope = await asyncio.wait_for(_collect(process, timeout=0.2), timeout=2.0)
    assert envelope.get("error") == "task_run_timeout"


@pytest.mark.asyncio
async def test_eval_worker_treats_none_remaining_as_unbounded() -> None:
    process = await _process(_SLOW_OK)
    ctx = SimpleNamespace(remaining_seconds=lambda: None)
    envelope = await asyncio.wait_for(
        _serve_eval_worker(process, ctx, timeout=0.1),
        timeout=2.0,
    )
    assert envelope.get("ok") is True


@pytest.mark.asyncio
async def test_eval_worker_uses_live_remaining_past_the_captured_timeout() -> None:
    process = await _process(_SLOW_OK)
    ctx = SimpleNamespace(remaining_seconds=lambda: 5.0)
    envelope = await asyncio.wait_for(
        _serve_eval_worker(process, ctx, timeout=0.1),
        timeout=2.0,
    )
    assert envelope.get("ok") is True
