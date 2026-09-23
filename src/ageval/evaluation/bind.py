"""Attempt result binding — the barrier between running and judging.

The Agent finishing is not a verdict. ``status`` is PASS or FAIL only when
the evaluator says so. A phase failure is ERROR. Timeout text is not a verdict.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_ERROR = "ERROR"
_VERDICTS = frozenset({STATUS_PASS, STATUS_FAIL})


@dataclass(frozen=True, slots=True)
class AttemptResult:
    """Flat Attempt result written to evidence and printed by the CLI."""

    status: str  # PASS | FAIL | ERROR
    score: float | None
    metrics: Mapping[str, Any]
    error_phase: str | None
    cleanup_warning: str | None
    evidence_path: str
    # Which box ran this Attempt, and which of its capabilities were used.
    kind: str
    capabilities_used: tuple[str, ...] = ()
    agent_invocations: int = 0
    gold_materialized_at: str = "evaluate"
    # Result.logs locates the Attempt evidence root; never a score input.
    logs: str | None = None
    # Run-phase limits key that was enforced, or None.
    limit: str | None = None
    facts: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_invocations": self.agent_invocations,
            "capabilities_used": list(self.capabilities_used),
            "cleanup_warning": self.cleanup_warning,
            "error": {"phase": self.error_phase} if self.error_phase else None,
            "evidence_path": self.evidence_path,
            "gold_materialized_at": self.gold_materialized_at,
            "kind": self.kind,
            "limit": self.limit,
            "logs": self.logs or self.evidence_path,
            "metrics": dict(self.metrics),
            "score": self.score,
            "status": self.status,
        }


def bind_result(
    *,
    evaluator_raw: Mapping[str, Any] | None,
    kind: str,
    capabilities_used: Sequence[str] = (),
    agent_invocations: int = 0,
    evidence_path: str,
    cleanup_warning: str | None = None,
    error_phase: str | None = None,
    limit: str | None = None,
    logs: str | None = None,
    facts: Sequence[Mapping[str, Any]] = (),
) -> AttemptResult:
    """Turn an evaluator verdict or a phase failure into the Attempt result.

    PASS and FAIL come only from the evaluator's ``status``. A phase failure,
    a missing verdict, or any other status is ERROR.
    """
    common: dict[str, Any] = {
        "cleanup_warning": cleanup_warning,
        "evidence_path": evidence_path,
        "kind": kind,
        "capabilities_used": tuple(capabilities_used),
        "agent_invocations": agent_invocations,
        "logs": logs if logs is not None else evidence_path,
        "limit": limit,
        "facts": tuple(facts),
    }
    if error_phase:
        return AttemptResult(
            status=STATUS_ERROR, score=None, metrics={}, error_phase=error_phase, **common
        )
    if evaluator_raw is None:
        return AttemptResult(
            status=STATUS_ERROR, score=None, metrics={}, error_phase="evaluate", **common
        )
    status = str(evaluator_raw.get("status") or "")
    if status not in _VERDICTS:
        return AttemptResult(
            status=STATUS_ERROR, score=None, metrics={}, error_phase="evaluate", **common
        )
    # Observational ``checks`` (if any) is not an input to the Attempt verdict.
    score = evaluator_raw.get("score")
    raw_metrics = evaluator_raw.get("metrics")
    return AttemptResult(
        status=status,
        score=float(score) if isinstance(score, int | float) else None,
        metrics=raw_metrics if isinstance(raw_metrics, dict) else {},
        error_phase=None,
        **common,
    )
