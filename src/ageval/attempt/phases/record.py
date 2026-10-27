"""record phase: collect, enrich, seal, then summary_enrich.

Plugins may shape each turn's payload; the ``trajectory_seal`` winner writes
the file. Each step runs even when an earlier step failed, and the phase
still fails if any step did. Collect/enrich/summary_enrich stay fail-open
in the sense that a later step is not skipped. Losing the sealed file fails
the phase. ``summary_enrich`` runs once after the seal step, successful or not.
"""

from __future__ import annotations

import json
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
        if not any(turns):
            inherited = inherited_display_rows(ctx)
            if inherited:
                turns = [inherited]

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


def inherited_display_rows(ctx: AttemptCtx) -> list[dict[str, Any]]:
    """Parent display trajectory for a fork that replayed a finished invoke.

    A completed invoke returns the old result and writes no new events. The
    parent's sealed ``trajectory.jsonl`` is that invoke. Copy it so the child
    page is not an empty trajectory. A cut inside the invoke is not this case:
    later parent lines must not be treated as the child's steps.
    """
    seq = getattr(ctx, "fork_checkpoint_seq", None)
    log = getattr(ctx, "activity", None)
    if not isinstance(seq, int) or isinstance(seq, bool) or log is None:
        return []
    records = getattr(log, "records", None)
    if not isinstance(records, list):
        return []
    completed_invoke = any(
        getattr(record, "seq", None) == seq
        and getattr(record, "kind", None) == "invoke"
        and getattr(record, "status", None) == "completed"
        for record in records
    )
    if not completed_invoke:
        return []
    prov = getattr(ctx, "fork_provenance", None)
    parent = prov.get("parent_attempt_id") if isinstance(prov, dict) else None
    if not isinstance(parent, str) or not parent or parent in {".", ".."} or "/" in parent:
        return []
    path = Path(ctx.dataset_root) / ".ageval" / "runs" / parent / "trajectory.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            copied = dict(row)
            copied["inherited"] = True
            rows.append(copied)
    return rows


def _fields(shaped: Any, original: dict[str, Any]) -> dict[str, Any]:
    """Accept a shaped payload only when it still carries the whole turn."""
    if isinstance(shaped, dict) and shaped.keys() >= original.keys():
        return {key: shaped[key] for key in original}
    return original
