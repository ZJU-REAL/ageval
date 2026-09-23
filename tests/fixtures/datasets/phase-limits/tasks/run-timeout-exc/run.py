"""A TimeoutExpired from run.py is not a run-phase limit."""

from __future__ import annotations

import subprocess

from ageval_sdk import RunContext, RunTerminal


async def run(ctx: RunContext) -> RunTerminal:
    del ctx
    raise subprocess.TimeoutExpired(cmd=["sleep", "1"], timeout=1)
