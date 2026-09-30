"""One upstream stall for a parent invoke whose executor result is not ok.

The parent owns the clock, the label, and the evidence fact. Plugins do not
sleep on their own while ``wall_time_seconds`` or ``evaluate_seconds`` keep
running. The interval is fixed. ``options.upstream_stall_seconds`` is the budget.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from ageval.config.profiles import require_upstream_stall_seconds

UPSTREAM_STALL_INTERVAL_SECONDS = 60
UPSTREAM_STALL_DEFAULT_SECONDS = 3600

_REASON_LIMIT = 500


def budget_seconds(raw: Any) -> int:
    """Omitted means the default. A present value must already be a valid budget."""
    if raw is None:
        return UPSTREAM_STALL_DEFAULT_SECONDS
    return require_upstream_stall_seconds(raw, location="options.upstream_stall_seconds")


class UpstreamStall:
    """Stall episode for one parent invoke.

    ``note_failure`` opens the episode and returns whether another full interval
    fits in the budget. ``wait`` sleeps that interval. A later failure stays in
    the same episode. Success, an exhausted budget, or ``not_repeatable`` closes
    it. ``claim`` tells the parent the executor already kept in-process state, so
    the outer loop must not start another invoke.
    """

    def __init__(
        self,
        *,
        budget_seconds: int,
        phase: str,
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
        now: Callable[[], datetime],
        on_event: Callable[[dict[str, Any]], None],
        on_freeze: Callable[[], None],
        on_thaw: Callable[[], None],
        on_fact: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self.budget_seconds = budget_seconds
        self.phase = phase
        self._monotonic = monotonic
        self._sleep = sleep
        self._now = now
        self._on_event = on_event
        self._on_freeze = on_freeze
        self._on_thaw = on_thaw
        self._on_fact = on_fact
        self._claimed = False
        self._open = False
        self._frozen = False
        self._spent = 0.0
        self._episode_started: float | None = None
        self._try_count = 0
        self._reason = ""
        self._started_at = ""

    @property
    def disabled(self) -> bool:
        return self.budget_seconds <= 0

    @property
    def claimed(self) -> bool:
        return self._claimed

    @property
    def episode_open(self) -> bool:
        return self._open

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def claim(self) -> None:
        self._claimed = True

    def note_failure(self, reason: str) -> bool:
        """Record one failed attempt. True means the caller should ``wait`` and retry."""
        if self.disabled:
            return False
        if not self._open:
            self._open_episode(reason)
        else:
            self._try_count += 1
            if reason:
                self._reason = reason[:_REASON_LIMIT]
        if self._remaining() >= UPSTREAM_STALL_INTERVAL_SECONDS:
            return True
        self._finish("budget_exhausted")
        return False

    def wait(self) -> None:
        self._emit("wait", seconds_until_next=UPSTREAM_STALL_INTERVAL_SECONDS)
        self._sleep(float(UPSTREAM_STALL_INTERVAL_SECONDS))

    def end_resumed(self) -> None:
        if not self._open:
            return
        self._try_count += 1
        self._finish("resumed")

    def mark_not_repeatable(self, reason: str) -> None:
        """One line, no sleep, and no time on the stall budget."""
        if self.disabled or self._open:
            return
        self._reason = (reason or "")[:_REASON_LIMIT]
        self._started_at = self._iso()
        self._try_count = 1
        self._emit("not_repeatable", seconds_until_next=0)
        self._on_fact("upstream_stall", self._detail("not_repeatable"))

    def abort(self) -> None:
        """Drop an open episode after a crash. Thaw the phase clock, write no fact."""
        if self._frozen:
            self._on_thaw()
            self._frozen = False
        self._episode_started = None
        self._open = False

    def _open_episode(self, reason: str) -> None:
        self._open = True
        self._reason = (reason or "")[:_REASON_LIMIT]
        self._started_at = self._iso()
        self._episode_started = self._monotonic()
        self._try_count = 1
        if not self._frozen:
            self._on_freeze()
            self._frozen = True
        self._emit("started", seconds_until_next=self._next_wait())

    def _finish(self, outcome: str) -> None:
        self._emit(outcome, seconds_until_next=0)
        self._on_fact("upstream_stall", self._detail(outcome))
        self._close_clock()
        self._open = False

    def _close_clock(self) -> None:
        if self._episode_started is not None:
            self._spent += max(0.0, self._monotonic() - self._episode_started)
            self._episode_started = None
        if self._frozen:
            self._on_thaw()
            self._frozen = False

    def _detail(self, outcome: str) -> dict[str, Any]:
        return {
            "reason": self._reason,
            "started_at": self._started_at,
            "try_count": self._try_count,
            "outcome": outcome,
        }

    def _remaining(self) -> float:
        live = 0.0
        if self._episode_started is not None:
            live = max(0.0, self._monotonic() - self._episode_started)
        return max(0.0, float(self.budget_seconds) - self._spent - live)

    def _next_wait(self) -> int:
        if self._remaining() >= UPSTREAM_STALL_INTERVAL_SECONDS:
            return UPSTREAM_STALL_INTERVAL_SECONDS
        return 0

    def _emit(self, outcome: str, *, seconds_until_next: int) -> None:
        self._on_event(
            {
                "outcome": outcome,
                "seconds_until_next": int(seconds_until_next),
                "remaining_budget": int(self._remaining()),
                "phase": self.phase,
            }
        )

    def _iso(self) -> str:
        moment = self._now()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


_CURRENT: ContextVar[UpstreamStall | None] = ContextVar("ageval_upstream_stall", default=None)


def bind_stall(stall: UpstreamStall | None) -> Token[UpstreamStall | None]:
    """Bind the stall for executors that retry inside this invoke (miniswe)."""
    return _CURRENT.set(stall)


def reset_stall(token: Token[UpstreamStall | None]) -> None:
    _CURRENT.reset(token)


def current_stall() -> UpstreamStall | None:
    return _CURRENT.get()
