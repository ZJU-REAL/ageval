"""Finish inside the run clock after setup used part of the environment clock."""

from __future__ import annotations

import time

from ageval_sdk import RunContext, RunTerminal


async def run(ctx: RunContext) -> RunTerminal:
    del ctx
    time.sleep(1)
    return RunTerminal.completed("fit")
