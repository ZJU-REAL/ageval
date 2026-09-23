"""AttemptCtx — the only object phases and plugins share.

The field list is deliberately closed. A phase or plugin that needs something
new must get it here explicitly, so "what can a plugin touch" stays readable.
PASS enters exactly once, through ``bind_evaluation``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ageval.config.model import LockedTaskConfig, thaw
from ageval.environments.protocol import EnvironmentProvider
from ageval.plugins.protocol import ExtensionGraph
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.services import ServiceTable
from ageval.runtime.cancellation import CancellationSignal


class EvaluationBindingError(RuntimeError):
    """Raised when something other than the evaluate phase tries to set the verdict."""


PhaseObserver = Callable[[str, str], None]
"""Live phase observer: called with (``"started"`` | ``"finished"``, phase name).

Observational only — phases never read it, and it never changes the sequence."""


@dataclass
class PhaseFact:
    """One recorded fact from a phase or a chain handler."""

    phase: str
    name: str
    detail: dict[str, Any]


@dataclass
class AttemptCtx:
    """Everything one Attempt needs; nothing more."""

    run_id: str
    trial_id: str
    attempt_id: str
    lock: LockedTaskConfig
    profile_id: str
    bindings: ExtensionGraph
    registry: ExtensionRegistry
    services: ServiceTable
    host: EnvironmentProvider
    evidence: Any
    cancellation: CancellationSignal
    # Engine-owned locations: the member task directory and its dataset root.
    task_root: Path
    dataset_root: Path
    # Isolated evaluate: a second EnvironmentProvider instance. None = same box.
    evaluate_host: EnvironmentProvider | None = None
    # Named scoring hosts (evaluation.environments). Bound at composition; started lazily.
    evaluate_hosts: dict[str, EnvironmentProvider] = field(default_factory=dict)
    started_evaluate_names: set[str] = field(default_factory=set)
    # Host-side upload sources. Phases never read the rest of the task tree.
    seed_dir: Path | None = None
    environment_src: Path | None = None
    evaluation_src: Path | None = None
    agent_service: Any = None
    deadline_monotonic: float | None = None
    keep_workspace: bool = False
    keep_vendor_raw: bool = False
    summary_extra: dict[str, Any] | None = None
    on_phase: PhaseObserver | None = None
    phase_facts: list[PhaseFact] = field(default_factory=list)
    phase: str = "created"
    evaluation_result: Any = None
    _writers_stopped: bool = False

    # --- verdict -------------------------------------------------------------

    def bind_evaluation(self, result: Any) -> None:
        """Bind the independent evaluator's result. The only source of PASS."""
        if self.phase != "evaluate":
            raise EvaluationBindingError(
                f"evaluation may only be bound from the evaluate phase (in {self.phase!r})"
            )
        if self.evaluation_result is not None:
            raise EvaluationBindingError("evaluation already bound for this Attempt")
        if not isinstance(result, dict):
            raise EvaluationBindingError("evaluator must return a dict")
        self.evaluation_result = result

    # --- budget --------------------------------------------------------------

    def arm_phase_budget(self, key: str) -> None:
        """Start this phase's clock from ``limits.<key>``.

        A missing lock leaves any caller-supplied deadline alone. A non-positive
        value leaves the phase unbounded. The parent Agent Service reads the
        same instant for invoke and session refusals.
        """
        lock = self.lock
        if lock is None:
            return
        limits = thaw(getattr(lock, "limits", None) or {})
        raw = limits.get(key) if isinstance(limits, dict) else None
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            self.deadline_monotonic = None
        else:
            self.deadline_monotonic = time.monotonic() + float(raw)
        self._push_agent_deadline()

    def _push_agent_deadline(self) -> None:
        service = self.agent_service
        if service is None:
            return
        parent = getattr(service, "service", None) or service
        if hasattr(parent, "deadline_monotonic"):
            parent.deadline_monotonic = self.deadline_monotonic

    def remaining_seconds(self) -> float | None:
        """Seconds left on the current phase clock, or None when unbounded."""
        if self.deadline_monotonic is None:
            return None
        return max(0.0, self.deadline_monotonic - time.monotonic())

    def phase_budget_exhausted(self) -> bool:
        remaining = self.remaining_seconds()
        return remaining is not None and remaining <= 0.0

    def assert_deadline(self) -> None:
        """Fail this phase when its clock is already out.

        Run does not use this: a run-phase limit is recorded and then scored.
        """
        if not self.phase_budget_exhausted():
            return
        token = {
            "environment": "environment_timeout",
            "evaluate": "evaluate_timeout",
        }.get(self.phase, "phase_budget_exceeded")
        raise TimeoutError(token)

    def note_limit_reached(self, name: str) -> None:
        """Record the first run-phase limit. Later hits do not replace it."""
        if self.limit_name() is not None:
            return
        self.record_fact("limit_reached", {"name": name})

    def limit_name(self) -> str | None:
        for fact in self.phase_facts:
            if fact.name != "limit_reached":
                continue
            value = fact.detail.get("name")
            if isinstance(value, str) and value:
                return value
        return None

    # --- writers -------------------------------------------------------------

    def mark_writers_stopped(self) -> None:
        self._writers_stopped = True

    def assert_writers_stopped(self) -> None:
        """Evaluate must not start while run-phase Agent writers can still write."""
        if not self._writers_stopped:
            raise RuntimeError("agent writers not confirmed stopped before evaluate")

    @property
    def scoring_host(self) -> EnvironmentProvider:
        """Singular scoring box. Named maps use ``evaluate_hosts`` instead."""
        return self.evaluate_host if self.evaluate_host is not None else self.host

    # --- facts ---------------------------------------------------------------

    def record_fact(self, name: str, detail: dict[str, Any] | None = None) -> None:
        self.phase_facts.append(PhaseFact(phase=self.phase, name=name, detail=dict(detail or {})))

    def facts_as_list(self) -> list[dict[str, Any]]:
        return [
            {"phase": f.phase, "name": f.name, **({"detail": f.detail} if f.detail else {})}
            for f in self.phase_facts
        ]
