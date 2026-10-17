"""record phase: collect, enrich, seal, then summary_enrich.

Plugins may shape each turn's payload; the ``trajectory_seal`` winner writes
the file. Each step runs even when an earlier step failed, and the phase
still fails if any step did. Collect/enrich/summary_enrich stay fail-open
in the sense that a later step is not skipped. Losing the sealed file fails
the phase. ``summary_enrich`` runs once after the seal step, successful or not.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.emit import emit
from ageval.evidence.invocation import read_invocation_payload
from ageval.evidence.slim import slim_sealed_attempt
from ageval.evidence.trajectory import turn_rows, write_evaluation_observation
from ageval.plugins.binding import bind_winner
from ageval.plugins.slots import (
    SUMMARY_ENRICH,
    TRAJECTORY_COLLECT,
    TRAJECTORY_ENRICH,
    TRAJECTORY_SEAL,
)

PHASE = "record"


async def run(ctx: AttemptCtx) -> None:
    ctx.phase = PHASE
    failures: list[BaseException] = []
    turns: list[list[dict[str, Any]]] = []

    async def step(name: str, fn: Callable[[], Awaitable[None]]) -> None:
        try:
            await fn()
        except Exception as exc:  # noqa: BLE001 — records record_step_failed
            ctx.record_fact(
                "record_step_failed",
                {"step": name, "error": f"{type(exc).__name__}: {exc}"},
            )
            failures.append(exc)

    async def fold() -> None:
        nonlocal turns
        turns = await _fold_invocations(ctx, ctx.evidence.list_invocations(), include_user=True)

    async def seal() -> None:
        impl = bind_winner(ctx.registry, ctx.bindings, TRAJECTORY_SEAL)
        plugin_id = ctx.bindings.winners[TRAJECTORY_SEAL].plugin_id
        ctx.services.register(TRAJECTORY_SEAL, impl, plugin_id=plugin_id)
        path = impl.seal(ctx, turns)
        if not path.is_file():
            raise RuntimeError("trajectory_seal did not write the trajectory file")
        ctx.record_fact("trajectory_recorded", {"turns": len(turns), "file": path.name})

    async def observe() -> None:
        eval_turns = await _fold_invocations(
            ctx, ctx.evidence.list_evaluation_invocations(), include_user=False
        )
        if not eval_turns:
            return
        obs = write_evaluation_observation(
            ctx.evidence.root,
            eval_turns,
            redaction_sentinels=ctx.evidence.sentinels,
        )
        ctx.record_fact(
            "evaluation_observation_recorded",
            {"turns": len(eval_turns), "file": obs.name},
        )

    async def vendor() -> None:
        if ctx.keep_vendor_raw:
            ctx.record_fact("vendor_raw_kept", {"keep_vendor_raw": True})
            return
        slim_sealed_attempt(ctx.evidence.root)
        ctx.record_fact("vendor_raw_dropped", {"keep_vendor_raw": False})

    async def summary() -> None:
        bag = await emit(ctx, SUMMARY_ENRICH, {})
        ctx.summary_extra = bag if isinstance(bag, dict) and bag else None

    await step("fold", fold)
    await step("seal", seal)
    await step("evaluation_observation", observe)
    await step("vendor_raw", vendor)
    await step("summary_enrich", summary)
    if failures:
        first = failures[0]
        raise RuntimeError(f"record step failed: {type(first).__name__}: {first}") from first


async def _fold_invocations(
    ctx: AttemptCtx,
    directories: list[Path],
    *,
    include_user: bool,
) -> list[list[dict[str, Any]]]:
    turns: list[list[dict[str, Any]]] = []
    for directory in directories:
        payload = read_invocation_payload(directory)
        shaped = await emit(ctx, TRAJECTORY_COLLECT, payload)
        shaped = await emit(ctx, TRAJECTORY_ENRICH, shaped)
        turns.append(turn_rows(**_fields(shaped, payload), include_user=include_user))
    return turns


def _fields(shaped: Any, original: dict[str, Any]) -> dict[str, Any]:
    """Accept a shaped payload only when it still carries the whole turn."""
    if isinstance(shaped, dict) and shaped.keys() >= original.keys():
        return {key: shaped[key] for key in original}
    return original
