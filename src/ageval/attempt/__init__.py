"""One Attempt, in order, in one place.

Read this file to know what happens and when. Each phase is a file under
``phases/``; inside a phase, ``emit(ctx, slot)`` runs the chain the lock already
ordered. Plugins change bindings — never this sequence.

Engine invariants live here, not in plugins: the lock and Attempt identity, the
phase clocks, ``cleanup`` always running, and PASS entering only through
``evaluate``.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.phases import cleanup, environment, evaluate, record, run

Phase = Callable[[AttemptCtx], Awaitable[None]]


def _failed_phase(ctx: AttemptCtx) -> str | None:
    for fact in ctx.phase_facts:
        if fact.name == "phase_failed":
            phase = fact.detail.get("phase")
            if isinstance(phase, str) and phase.strip():
                return phase
    return None


def _note_phase_failed(ctx: AttemptCtx, exc: BaseException) -> None:
    if _failed_phase(ctx) is not None:
        return
    ctx.record_fact(
        "phase_failed",
        {"phase": ctx.phase, "error": f"{type(exc).__name__}: {exc}"},
    )


async def run_attempt(ctx: AttemptCtx) -> None:
    """Open the box, run the task, judge it, record it, tear the box down.

    A phase failure is an outcome, not a crash: it is recorded against the
    first phase that failed and the Attempt still produces a result document.
    After environment starts, ``record`` still seals whatever invoke scratch
    exists so Viewer / upload can read ``trajectory.jsonl`` on FAIL/ERROR.
    Cancellation (``BaseException``) still propagates; cleanup always runs.
    """
    should_record = False
    try:
        await _timed(ctx, environment.PHASE, environment.run)
        should_record = True
        await _timed(ctx, run.PHASE, run.run)
        try:
            await _timed(ctx, evaluate.PHASE, evaluate.run)
        except Exception as exc:  # noqa: BLE001 — evaluate ERROR still seals
            _note_phase_failed(ctx, exc)
    except Exception as exc:  # noqa: BLE001 — the phase name is the operator's answer
        _note_phase_failed(ctx, exc)
    finally:
        if should_record:
            try:
                await _timed(ctx, record.PHASE, record.run)
            except Exception as exc:  # noqa: BLE001 — do not hide an earlier phase
                if _failed_phase(ctx) is None:
                    _note_phase_failed(ctx, exc)
                else:
                    ctx.record_fact(
                        "record_warning",
                        {"error": f"{type(exc).__name__}: {exc}"},
                    )
        await _timed(ctx, cleanup.PHASE, cleanup.run)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def _timed(ctx: AttemptCtx, name: str, phase: Phase) -> None:
    """Run one phase, notify the live observer, and record how long it took."""
    if ctx.on_phase is not None:
        ctx.on_phase("started", name)
    started_mono = time.monotonic()
    started_at = _utc_now()
    try:
        await phase(ctx)
    finally:
        if ctx.on_phase is not None:
            ctx.on_phase("finished", name)
        ctx.record_fact(
            "phase_finished",
            {
                "phase": ctx.phase,
                "duration_ms": round((time.monotonic() - started_mono) * 1000.0, 3),
                "started_at": started_at,
                "finished_at": _utc_now(),
            },
        )


__all__ = ["AttemptCtx", "run_attempt"]
