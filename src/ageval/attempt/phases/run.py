"""run phase: hand control to the task's own ``run.py``, in a child process.

The control plane never imports task code. Agent invocations travel back over
the Agent Service socket, so the task gets a session without ever holding a
credential or the box handle.
"""

from __future__ import annotations

import inspect
from typing import Any

from ageval.attempt.artifact_harvest import harvest_workspace_artifacts
from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.emit import emit
from ageval.evaluation.error_record import RecordedError, message_from_envelope
from ageval.plugins.slots import AFTER_RUN, BEFORE_RUN

PHASE = "run"


# Worker envelope when the run clock kills the task process. Not a verdict.
_RUN_WORKER_TIMEOUT = "task_run_timeout"


async def run(ctx: AttemptCtx) -> None:
    ctx.phase = PHASE
    ctx.arm_phase_budget("wall_time_seconds")
    if ctx.phase_budget_exhausted():
        ctx.note_limit_reached("wall_time_seconds")
    await emit(ctx, BEFORE_RUN)
    try:
        try:
            if ctx.phase_budget_exhausted() and ctx.limit_name() == "wall_time_seconds":
                outcome = {"ok": False, "error": "wall_time_exceeded"}
            elif ctx.replay_plan is not None:
                from ageval.attempt.replay_exec import execute_recorded_actions

                outcome = await execute_recorded_actions(ctx)
            else:
                outcome = await _run_task_entry(ctx)
        except Exception as exc:
            # A limit already enforced ends the phase without phase_failed.
            # The worker exception stays on the task_run fact; evaluate still runs.
            if ctx.limit_name() is None:
                raise
            outcome = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if not isinstance(outcome, dict):
            outcome = {"ok": False, "error": "task_run_failed"}
        if outcome.get("error") == _RUN_WORKER_TIMEOUT:
            ctx.note_limit_reached("wall_time_seconds")
        ctx.record_fact("task_run", outcome)
        if outcome.get("ok") is not True and ctx.limit_name() is None:
            title = str(outcome.get("error") or "task_run_failed")
            raise RecordedError(title, message_from_envelope(outcome))
    finally:
        if ctx.agent_service is not None:
            await _seal_run_agent_service(ctx)
        # Solver writers cannot write after this point. Harvest still runs, and
        # seal_run is recorded only after that copy succeeds.
        ctx.mark_writers_stopped()
    await harvest_workspace_artifacts(ctx)
    if ctx.replay_plan is not None:
        from ageval.attempt.replay_exec import note_artifact_divergence

        note_artifact_divergence(ctx)
    _log_seal_run(ctx)
    await emit(ctx, AFTER_RUN)
    _raise_fatal_recovery(ctx)


def _log_seal_run(ctx: AttemptCtx) -> None:
    log = ctx.activity
    if log is None or log.has_completed_phase("seal_run"):
        return
    log.append(
        request_id="phase_seal_run",
        kind="phase",
        status="completed",
        payload={
            "phase": "seal_run",
            "elapsed_ms": ctx.active_elapsed_ms(),
            "limit_reached": ctx.limit_name(),
            "checkpoint_seq": None,
        },
    )


def _raise_fatal_recovery(ctx: AttemptCtx) -> None:
    service = ctx.agent_service
    parent = getattr(service, "service", None) if service is not None else None
    fatal = getattr(parent, "fatal_error", None)
    if not isinstance(fatal, str) or not fatal:
        return
    raise RecordedError(fatal, fatal)


async def _run_task_entry(ctx: AttemptCtx) -> dict[str, object]:
    from ageval.runtime.task_launch import launch_task_worker

    return await launch_task_worker(ctx)


async def _seal_run_agent_service(ctx: AttemptCtx) -> None:
    seal = getattr(ctx.agent_service, "seal_run", None)
    if callable(seal):
        await _maybe_await(seal())
        return
    stop = getattr(ctx.agent_service, "stop", None)
    if stop is None:
        return
    await _maybe_await(stop())


async def _maybe_await(result: Any) -> None:
    if inspect.isawaitable(result):
        await result
