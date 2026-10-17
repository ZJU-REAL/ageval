"""Checks that a sealed Attempt trajectory is safe to clean up after.

``result.json`` is the verdict document written after the pipeline returns.
The seal this module checks is the trajectory, which the record phase writes
before cleanup. Every terminal ``usage`` is an object: reported fields, or
``unavailable`` with a reason. JSON null is not a usage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ageval.evidence.trajectory import TRAJECTORY_FILENAME
from ageval.model.usage import REASONS

_INVOCATION_DROP = (
    "request.json",
    "events.jsonl",
    "final-response.json",
    "metadata.json",
    "stderr.txt",
)
_MEASURED = ("prompt_tokens", "completion_tokens", "cached_tokens", "cost_usd")


class SealInvariantError(RuntimeError):
    """The trajectory exists but does not meet the seal."""


def usage_document_ok(usage: Any) -> bool:
    """True for a sealed usage object. Null, a list, and an empty object fail."""
    if not isinstance(usage, dict) or not usage:
        return False
    reason = usage.get("unavailable")
    if reason is not None:
        return isinstance(reason, str) and reason in REASONS
    return any(key in usage for key in _MEASURED)


def assert_sealed_invariants(root: Path, *, keep_vendor_raw: bool) -> None:
    """Raise ``SealInvariantError`` when the trajectory seal is incomplete.

    ``keep_vendor_raw`` false means slim already ran: invocation scratch and
    ``backend_raw`` must be gone. True leaves whatever the executor wrote.
    """
    trajectory = root / TRAJECTORY_FILENAME
    if not trajectory.is_file():
        raise SealInvariantError("trajectory.jsonl missing")
    _assert_terminals(trajectory)
    if not keep_vendor_raw and _vendor_raw_left(root):
        raise SealInvariantError("vendor raw remains after slim")


def _assert_terminals(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SealInvariantError(f"trajectory unreadable: {exc}") from exc
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SealInvariantError(f"trajectory line {line_no} is not json") from exc
        if not isinstance(obj, dict) or obj.get("type") != "terminal":
            continue
        if not usage_document_ok(obj.get("usage")):
            raise SealInvariantError(f"terminal usage on line {line_no} is not sealed")


def _vendor_raw_left(root: Path) -> bool:
    if (root / "agent" / "events.jsonl").is_file():
        return True
    if (root / "evaluation" / "events.jsonl").is_file():
        return True
    if (root / "evaluation" / "evaluator_raw.json").is_file():
        return True
    for relative in ("agent/invocations", "evaluation/invocations"):
        inv_root = root / relative
        if not inv_root.is_dir():
            continue
        for child in inv_root.iterdir():
            if not child.is_dir():
                continue
            if (child / "backend_raw").exists():
                return True
            if any((child / name).is_file() for name in _INVOCATION_DROP):
                return True
    return False
