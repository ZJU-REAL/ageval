"""Must not run: setup.sh outlives the environment clock."""

from __future__ import annotations

from ageval_sdk import RunContext, RunTerminal


async def run(ctx: RunContext) -> RunTerminal:
    del ctx
    return RunTerminal.completed("should-not-run")
