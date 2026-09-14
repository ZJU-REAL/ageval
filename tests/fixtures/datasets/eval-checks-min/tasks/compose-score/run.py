"""Solver path: publish an artifact. Does not open a judge session."""

from __future__ import annotations

from ageval_sdk import RunContext, RunTerminal


async def run(ctx: RunContext) -> RunTerminal:
    ctx.publish_json("result", {"ok": True})
    return RunTerminal.completed("ok")
