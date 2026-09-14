"""Run the task's ``evaluator.py`` in a parent subprocess, after gold is ready.

Same shape as ``run.py``: process boundary, host Agent Service socket, no
``import evaluator``. Isolated evaluate still materializes gold and snapshots
onto the scoring host so ACP attach_stdio sees them; the evaluator process
itself stays on the parent.
"""

from __future__ import annotations

from typing import Any


async def evaluate_in_box(ctx: Any) -> dict[str, Any]:
    """Launch the evaluator worker and return its verdict document."""
    from ageval.runtime.task_launch import launch_eval_worker

    envelope = await launch_eval_worker(ctx)
    ctx.record_fact(
        "evaluator_exec",
        {"exit_code": envelope.get("exit_code"), "parent_worker": True},
    )
    if envelope.get("ok") is not True:
        error = str(envelope.get("error") or "evaluator_failed")
        detail = str(envelope.get("message") or envelope.get("stderr") or "")[-500:]
        raise RuntimeError(f"{error}: {detail}" if detail else error)
    verdict = envelope.get("verdict")
    if not isinstance(verdict, dict):
        raise RuntimeError("evaluator produced no verdict document")
    ctx.evidence.write_evaluation("evaluator_raw", verdict)
    from ageval.evidence.checks import persist_evaluation_checks

    persist_evaluation_checks(ctx.evidence, verdict)
    return verdict
