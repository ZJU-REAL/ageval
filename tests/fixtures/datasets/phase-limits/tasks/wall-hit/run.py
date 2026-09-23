"""Sleep past the run clock. The worker is killed; evaluate still scores."""

from __future__ import annotations

import time

from ageval_sdk import RunContext, RunTerminal


async def run(ctx: RunContext) -> RunTerminal:
    del ctx
    time.sleep(30)
    return RunTerminal.completed("slept")
