"""cleanup phase: the box always comes down.

``run_attempt`` calls this from ``finally``. A plugin may report on cleanup; no
plugin can skip it.
"""

from __future__ import annotations

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.emit import emit
from ageval.plugins.slots import CLEANUP_REPORT

PHASE = "cleanup"


async def run(ctx: AttemptCtx) -> None:
    previous = ctx.phase
    ctx.phase = PHASE
    if ctx.suspended:
        # Leave the box running so resume can attach. A checkpoint already exists.
        ctx.record_fact("environment_suspended", {"deleted": False, "kept_running": True})
        await emit(ctx, CLEANUP_REPORT, ctx.facts_as_list())
        return
    delete = not ctx.keep_workspace
    errors: list[str] = []
    scoring = ctx.evaluate_host
    if scoring is not None and scoring is not ctx.host:
        try:
            await scoring.stop(delete=delete)
            ctx.record_fact("evaluate_host_stopped", {"deleted": delete})
        except Exception as exc:  # noqa: BLE001 — cleanup failure is a warning, not a verdict
            errors.append(f"{type(exc).__name__}: {exc}")
    for name in list(ctx.started_evaluate_names):
        named = ctx.evaluate_hosts.get(name)
        if named is None or named is ctx.host or named is scoring:
            continue
        try:
            await named.stop(delete=delete)
            ctx.record_fact("evaluate_host_stopped", {"deleted": delete, "name": name})
        except Exception as exc:  # noqa: BLE001 — cleanup failure is a warning, not a verdict
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    try:
        await ctx.host.stop(delete=delete)
        ctx.record_fact("environment_stopped", {"deleted": delete})
    except Exception as exc:  # noqa: BLE001 — cleanup failure is a warning, not a verdict
        errors.append(f"{type(exc).__name__}: {exc}")
    if errors:
        ctx.record_fact(
            "cleanup_warning",
            {"error": "; ".join(errors), "failed_phase": previous},
        )
    await emit(ctx, CLEANUP_REPORT, ctx.facts_as_list())
