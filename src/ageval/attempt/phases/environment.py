"""environment phase: open the box, put the task in it, let plugins prepare it.

Slot order here is the authority. ``environment_setup`` is the last slot, not a
separate provision phase: by the time ``run`` starts, the box is ready.

What goes in: the task's ``data/`` seed and whatever the plugins prepare. Gold
is not among them — it arrives in the evaluate phase, after the Agent stops.
"""

from __future__ import annotations

from typing import Any

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


async def _finish_rebuild(ctx: AttemptCtx) -> None:
    """Replay system effects, then restore the latest checkpoint onto the new box."""
    from ageval.attempt.recover import restore_checkpoint
    from ageval.environments.box_state import write_cursor
    from ageval.evaluation.error_record import RecordedError
    from ageval.evidence.store import AGENT_BOX_REL

    log = ctx.activity
    if log is None:
        return
    try:
        for record in log.completed_system_effect_tools():
            await _replay_system_effect(ctx, record)
        seq = log.last_checkpoint_seq()
        if seq is not None:
            restore_checkpoint(ctx, seq)
            from ageval.attempt.recover import attempt_state_dir

            write_cursor(attempt_state_dir(ctx), seq=seq, request_id=f"seq_{seq}")
        push = getattr(ctx.host, "push_restored_box", None)
        if callable(push):
            await push(ctx.evidence.path(AGENT_BOX_REL))
    except RecordedError:
        raise
    except Exception as exc:  # noqa: BLE001 — rebuild failure is a terminal Attempt error
        raise RecordedError("recovery_rebuild_failed", str(exc)) from exc


async def _replay_system_effect(ctx: AttemptCtx, completed: Any) -> None:
    from ageval.evaluation.error_record import RecordedError

    log = ctx.activity
    inflight = None
    if log is not None:
        for record in log.records_for(kind="tool_call", request_id=completed.request_id):
            if record.status == "in_flight":
                inflight = record
    arguments = inflight.payload.get("arguments") if inflight is not None else {}
    command = arguments.get("command") if isinstance(arguments, dict) else None
    if isinstance(command, str):
        argv = ["sh", "-c", command]
    elif isinstance(command, list):
        argv = [str(part) for part in command]
    else:
        raise RecordedError(
            "recovery_rebuild_failed",
            f"system effect {completed.request_id} has no command",
        )
    timeout = inflight.payload.get("timeout_sec") if inflight is not None else None
    result = await ctx.host.exec(
        argv,
        timeout_sec=float(timeout) if isinstance(timeout, int | float) else None,
    )
    expected = completed.payload.get("exit_code")
    if (
        isinstance(expected, int)
        and not isinstance(expected, bool)
        and result.exit_code != expected
    ):
        raise RecordedError(
            "recovery_rebuild_failed",
            f"system effect {completed.request_id} exited {result.exit_code}",
        )


async def run(ctx: AttemptCtx) -> None:
    ctx.phase = PHASE
    ctx.arm_phase_budget("environment_seconds")
    if ctx.recovery_attached:
        kind = getattr(ctx.host, "kind", "")
        ctx.record_fact("environment_started", {"kind": kind, "recovered": "attached"})
        return
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
    if ctx.recovery_rebuild:
        await _finish_rebuild(ctx)
    await emit(ctx, AFTER_ENVIRONMENT)
    if ctx.activity is not None:
        from ageval.attempt.recover import publish_environment_handle

        publish_environment_handle(ctx)
