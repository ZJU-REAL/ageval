"""Typed invoke usage. A missing measurement is a reason, never JSON null.

``Usage`` carries first-class token and cost fields the backend actually
reported. ``UsageUnavailable`` is the other arm: nothing was reported, the
clock fired before numbers arrived, the usage payload did not parse, or a
timeout kept only a partial bag. Suite totals bill ``Usage`` only.
``partial`` may still hold the numbers that arrived; those numbers are not
a bill and are not a zero.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

UsageReason = Literal["not_reported", "lost_on_timeout", "parse_failed", "partial"]

REASONS: frozenset[str] = frozenset({"not_reported", "lost_on_timeout", "parse_failed", "partial"})


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value


def _numbers(
    raw: Mapping[str, Any] | None,
) -> tuple[int | None, int | None, int | None, float | int | None]:
    if not isinstance(raw, Mapping):
        return None, None, None, None
    prompt = _as_int(raw.get("prompt_tokens"))
    if prompt is None:
        prompt = _as_int(raw.get("input_tokens"))
    completion = _as_int(raw.get("completion_tokens"))
    if completion is None:
        completion = _as_int(raw.get("output_tokens"))
    cached = _as_int(raw.get("cached_tokens"))
    if cached is None:
        cached = _as_int(raw.get("cached_read_tokens"))
    cost = _as_number(raw.get("cost_usd"))
    return prompt, completion, cached, cost


def _measured(
    prompt: int | None,
    completion: int | None,
    cached: int | None,
    cost: float | int | None,
) -> bool:
    return any(item is not None for item in (prompt, completion, cached, cost))


def _seal_fields(
    prompt: int | None,
    completion: int | None,
    cached: int | None,
    cost: float | int | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if prompt is not None:
        out["prompt_tokens"] = prompt
    if completion is not None:
        out["completion_tokens"] = completion
    if cached is not None:
        out["cached_tokens"] = cached
    if cost is not None:
        out["cost_usd"] = cost
    return out


@dataclass(frozen=True, slots=True, eq=False)
class Usage:
    """First-class counts the backend reported. Empty fields stay omitted."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: float | int | None = None

    def __bool__(self) -> bool:
        return _measured(
            self.prompt_tokens, self.completion_tokens, self.cached_tokens, self.cost_usd
        )

    def __hash__(self) -> int:
        return hash((self.prompt_tokens, self.completion_tokens, self.cached_tokens, self.cost_usd))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Usage):
            return (
                self.prompt_tokens == other.prompt_tokens
                and self.completion_tokens == other.completion_tokens
                and self.cached_tokens == other.cached_tokens
                and self.cost_usd == other.cost_usd
            )
        if isinstance(other, Mapping):
            return self.to_sealed() == dict(other)
        return NotImplemented

    def __contains__(self, key: object) -> bool:
        return key in self.to_sealed()

    def __getitem__(self, key: str) -> Any:
        sealed = self.to_sealed()
        if key not in sealed:
            raise KeyError(key)
        return sealed[key]

    def to_sealed(self) -> dict[str, Any]:
        return _seal_fields(
            self.prompt_tokens, self.completion_tokens, self.cached_tokens, self.cost_usd
        )


@dataclass(frozen=True, slots=True, eq=False)
class UsageUnavailable:
    """A sealed reason. ``partial`` may carry numbers that must not be billed."""

    reason: UsageReason
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: float | int | None = None

    def __bool__(self) -> bool:
        return _measured(
            self.prompt_tokens, self.completion_tokens, self.cached_tokens, self.cost_usd
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.reason,
                self.prompt_tokens,
                self.completion_tokens,
                self.cached_tokens,
                self.cost_usd,
            )
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, UsageUnavailable):
            return (
                self.reason == other.reason
                and self.prompt_tokens == other.prompt_tokens
                and self.completion_tokens == other.completion_tokens
                and self.cached_tokens == other.cached_tokens
                and self.cost_usd == other.cost_usd
            )
        if isinstance(other, Mapping):
            return self.to_sealed() == dict(other)
        return NotImplemented

    def __contains__(self, key: object) -> bool:
        return key in self.to_sealed()

    def __getitem__(self, key: str) -> Any:
        sealed = self.to_sealed()
        if key not in sealed:
            raise KeyError(key)
        return sealed[key]

    def to_sealed(self) -> dict[str, Any]:
        out = _seal_fields(
            self.prompt_tokens, self.completion_tokens, self.cached_tokens, self.cost_usd
        )
        out["unavailable"] = self.reason
        return out


NOT_REPORTED = UsageUnavailable("not_reported")
LOST_ON_TIMEOUT = UsageUnavailable("lost_on_timeout")


def _unavailable_from(
    raw: Mapping[str, Any],
    prompt: int | None,
    completion: int | None,
    cached: int | None,
    cost: float | int | None,
) -> UsageUnavailable | None:
    reason = raw.get("unavailable")
    if not isinstance(reason, str) or reason not in REASONS:
        return None
    return UsageUnavailable(
        reason,  # type: ignore[arg-type]
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=cached,
        cost_usd=cost,
    )


def _with_reason(
    reason: UsageReason,
    prompt: int | None,
    completion: int | None,
    cached: int | None,
    cost: float | int | None,
) -> UsageUnavailable:
    if reason == "not_reported" and not _measured(prompt, completion, cached, cost):
        return NOT_REPORTED
    if reason == "lost_on_timeout" and not _measured(prompt, completion, cached, cost):
        return LOST_ON_TIMEOUT
    return UsageUnavailable(
        reason,
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=cached,
        cost_usd=cost,
    )


def adopt_usage(
    raw: Any,
    *,
    timeout: bool = False,
    partial: bool = False,
    parse_failed: bool = False,
) -> Usage | UsageUnavailable:
    """Turn a normalize dict, ``None``, or an existing value into the union.

    A timeout with numbers is ``partial``. A timeout with no numbers is
    ``lost_on_timeout``. A parsed usage payload that is not a timeout and
    has numbers is ``Usage``. Everything else with no numbers is
    ``not_reported``, unless ``parse_failed`` names that reason.
    """
    if isinstance(raw, UsageUnavailable):
        if timeout and raw.reason == "not_reported":
            if raw:
                return _with_reason(
                    "partial",
                    raw.prompt_tokens,
                    raw.completion_tokens,
                    raw.cached_tokens,
                    raw.cost_usd,
                )
            return LOST_ON_TIMEOUT
        return raw
    if isinstance(raw, Usage):
        prompt, completion, cached, cost = (
            raw.prompt_tokens,
            raw.completion_tokens,
            raw.cached_tokens,
            raw.cost_usd,
        )
    else:
        prompt, completion, cached, cost = _numbers(raw if isinstance(raw, Mapping) else None)
        if isinstance(raw, Mapping):
            marked = _unavailable_from(raw, prompt, completion, cached, cost)
            if marked is not None and not timeout and not partial and not parse_failed:
                return marked
    has = _measured(prompt, completion, cached, cost)
    if parse_failed:
        return _with_reason("parse_failed", prompt, completion, cached, cost)
    if timeout:
        return _with_reason(
            "partial" if has else "lost_on_timeout", prompt, completion, cached, cost
        )
    if partial and has:
        return _with_reason("partial", prompt, completion, cached, cost)
    if has:
        return Usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            cached_tokens=cached,
            cost_usd=cost,
        )
    return NOT_REPORTED


def to_sealed_document(raw: Any) -> dict[str, Any]:
    """JSON object for evidence. Never null and never an empty object."""
    if isinstance(raw, Usage | UsageUnavailable):
        sealed = raw.to_sealed()
    else:
        sealed = adopt_usage(raw).to_sealed()
    return sealed or NOT_REPORTED.to_sealed()


def is_measured_usage(raw: Any) -> bool:
    """True when a finished turn reported billable usage.

    ``UsageUnavailable`` is not a measurement, including ``partial`` numbers.
    A non-empty mapping without ``unavailable`` still counts, so callers that
    have not adopted yet keep the old health check.
    """
    if raw is None or isinstance(raw, UsageUnavailable):
        return False
    if isinstance(raw, Usage):
        return bool(raw)
    if isinstance(raw, Mapping):
        if isinstance(raw.get("unavailable"), str):
            return False
        return bool(raw)
    return False
