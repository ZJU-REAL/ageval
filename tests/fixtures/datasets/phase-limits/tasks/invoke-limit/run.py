"""A refused run-phase invoke, then an exception. Evaluate still scores."""

from __future__ import annotations

from ageval_sdk import RunContext, RunTerminal


async def run(ctx: RunContext) -> RunTerminal:
    async with ctx.agent.session("solver") as session:
        await session.invoke("ping")
    raise RuntimeError("after-quota")
