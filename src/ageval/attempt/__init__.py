"""One Attempt, in order, in one place.

Read this file to know what happens and when. Each phase is a file under
``phases/``; inside a phase, ``emit(ctx, slot)`` runs the chain the lock already
ordered. Plugins change bindings — never this sequence.

Engine invariants live here, not in plugins: the lock and Attempt identity, the
phase clocks, ``cleanup`` always running, and PASS entering only through
``evaluate``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.phases import cleanup, environment, evaluate, record, run
from ageval.evaluation.error_record import error_record_from_exception
from ageval.evidence.invariants import SealInvariantError, assert_sealed_invariants
from ageval.evidence.trajectory import TRAJECTORY_FILENAME

_ATTEMPT_PHASES = frozenset({"environment", "run", "evaluate", "record"})

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
    phase = ctx.phase if ctx.phase in _ATTEMPT_PHASES else None
    ctx.record_fact("phase_failed", error_record_from_exception(exc, phase=phase))


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
        if not (ctx.recovery_attached and _phase_done(ctx, environment.PHASE)):
            await _timed(ctx, environment.PHASE, environment.run)
        should_record = True
        if _phase_done(ctx, "seal_run"):
            ctx.mark_writers_stopped()
            _seal_solver_profile(ctx)
        else:
            await _timed(ctx, run.PHASE, run.run)
        try:
            if _phase_done(ctx, evaluate.PHASE):
                _restore_verdict(ctx)
            else:
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
            _assert_sealed(ctx)
        await _timed(ctx, cleanup.PHASE, cleanup.run)


async def run_regrade(ctx: AttemptCtx) -> None:
    """Score a harvested snapshot. The task ``run`` phase does not run.

    The box still starts so evaluate can copy ``task-artifacts/`` and
    ``verifier-collect/`` onto the scoring host. Collect commands do not run.
    ``environment_setup`` and the agent probe do not run.
    """
    ctx.regrade = True
    should_record = False
    try:
        ctx.phase = environment.PHASE
        await ctx.host.preflight()
        await ctx.host.start(force_build=ctx.lock.force_build)
        ctx.record_fact("environment_started", {"kind": ctx.host.kind, "regrade": True})
        ctx.mark_writers_stopped()
        _seal_solver_profile(ctx)
        should_record = True
        await _timed(ctx, evaluate.PHASE, evaluate.run)
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
            _assert_sealed(ctx)
        await _timed(ctx, cleanup.PHASE, cleanup.run)


def _assert_sealed(ctx: AttemptCtx) -> None:
    """Check the trajectory seal before cleanup. A missing file is not a second failure.

    Record stubs and a seal step that never wrote the file leave no trajectory.
    Those cases already have a phase or record fact. A written trajectory that
    breaks the seal is its own fact, and does not replace an earlier phase.
    """
    root = ctx.evidence.root
    if not (root / TRAJECTORY_FILENAME).is_file():
        return
    try:
        assert_sealed_invariants(root, keep_vendor_raw=ctx.keep_vendor_raw)
    except SealInvariantError as exc:
        ctx.record_fact("seal_invariant_failed", {"error": str(exc)})
        if _failed_phase(ctx) is None:
            _note_phase_failed(ctx, exc)
        else:
            ctx.record_fact("record_warning", {"error": f"seal_invariant: {exc}"})


def _seal_solver_profile(ctx: AttemptCtx) -> None:
    """The run-phase profile stays sealed so evaluate cannot start the agent."""
    parent = getattr(ctx.agent_service, "service", None)
    seal = getattr(parent, "seal_profile_ids", None)
    if not callable(seal) or not ctx.profile_id:
        return
    seal([ctx.profile_id])


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _phase_done(ctx: AttemptCtx, name: str) -> bool:
    log = ctx.activity
    if log is None:
        return False
    return bool(log.has_completed_phase(name))


def _restore_verdict(ctx: AttemptCtx) -> None:
    path = ctx.evidence.root / "evaluation" / "evaluator_raw.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    if isinstance(data, dict):
        ctx.evaluation_result = data


def _log_phase(ctx: AttemptCtx, name: str, status: str) -> None:
    log = ctx.activity
    if log is None or name not in _ATTEMPT_PHASES:
        return
    if status == "in_flight":
        if log.has_phase_status(name, "in_flight") or log.has_completed_phase(name):
            return
        log.append(
            request_id=f"phase_{name}",
            kind="phase",
            status="in_flight",
            payload={"phase": name},
        )
        return
    if log.has_completed_phase(name):
        return
    from ageval.attempt.recover import capture_box

    def prepare(seq: int) -> dict[str, int | None]:
        return {"checkpoint_seq": capture_box(ctx, seq)}

    log.append(
        request_id=f"phase_{name}",
        kind="phase",
        status="completed",
        payload={
            "phase": name,
            "elapsed_ms": ctx.active_elapsed_ms(),
            "limit_reached": ctx.limit_name(),
            "checkpoint_seq": None,
        },
        prepare=prepare,
    )


async def _timed(ctx: AttemptCtx, name: str, phase: Phase) -> None:
    """Run one phase, notify the live observer, and record how long it took."""
    if ctx.on_phase is not None:
        ctx.on_phase("started", name)
    started_mono = time.monotonic()
    started_at = _utc_now()
    _log_phase(ctx, name, "in_flight")
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
        _log_phase(ctx, name, "completed")


__all__ = ["AttemptCtx", "run_attempt", "run_regrade"]
