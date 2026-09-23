"""environment phase: open the box, put the task in it, let plugins prepare it.

Slot order here is the authority. ``environment_setup`` is the last slot, not a
separate provision phase: by the time ``run`` starts, the box is ready.

What goes in: the task's ``data/`` seed and whatever the plugins prepare. Gold
is not among them — it arrives in the evaluate phase, after the Agent stops.
"""

from __future__ import annotations

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.emit import emit
from ageval.environments.protocol import WORKSPACE_PATH
from ageval.plugins.slots import (
    AFTER_ENVIRONMENT,
    AFTER_ENVIRONMENT_READY,
    BEFORE_ENVIRONMENT,
    ENVIRONMENT_SETUP,
)

PHASE = "environment"


async def run(ctx: AttemptCtx) -> None:
    ctx.phase = PHASE
    ctx.arm_phase_budget("environment_seconds")
    await emit(ctx, BEFORE_ENVIRONMENT)
    await ctx.host.start(force_build=ctx.lock.force_build)
    ctx.assert_deadline()
    ctx.record_fact("environment_started", {"kind": ctx.host.kind})
    if ctx.seed_dir is not None and ctx.seed_dir.is_dir():
        await ctx.host.upload(ctx.seed_dir, WORKSPACE_PATH)
        ctx.record_fact("seed_uploaded", {"source": ctx.seed_dir.name})
    # Agent runtime probe / HOME preparation happens here, before task setup.
    await emit(ctx, AFTER_ENVIRONMENT_READY)
    ctx.assert_deadline()
    await emit(ctx, ENVIRONMENT_SETUP)
    ctx.assert_deadline()
    await emit(ctx, AFTER_ENVIRONMENT)
