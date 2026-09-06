"""Roll attempt token/cost/duration into suite ``metrics.usage``.

Written at suite summary / upload. Observational — not PASS, not a bill.
Hub Pareto reads the stored bag; it does not re-price on every page load.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ageval.application.model_directory import estimate_cost_usd, load_model_pin
from ageval.config.errors import ConfigError
from ageval.evidence.locators import resolve_attempt_run_dir

_TRAJECTORY = "trajectory.jsonl"


def _as_int(val: Any) -> int | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float) and val == int(val):
        return int(val)
    return None


def _as_float(val: Any) -> float | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    return None


def usage_from_mapping(usage: Mapping[str, Any] | None) -> dict[str, Any]:
    """First-class token/cost fields from a sealed terminal.usage object."""
    if not isinstance(usage, Mapping):
        return {}
    prompt = _as_int(usage.get("prompt_tokens"))
    if prompt is None:
        prompt = _as_int(usage.get("input_tokens"))
    completion = _as_int(usage.get("completion_tokens"))
    if completion is None:
        completion = _as_int(usage.get("output_tokens"))
    cached = _as_int(usage.get("cached_tokens"))
    if cached is None:
        cached = _as_int(usage.get("cached_read_tokens"))
    cost = _as_float(usage.get("cost_usd"))
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


def usage_from_trajectory(path: Path) -> dict[str, Any]:
    """Last ``terminal.usage`` on an Attempt trajectory (one file per Attempt)."""
    if not path.is_file():
        return {}
    last: dict[str, Any] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict) or obj.get("type") != "terminal":
                    continue
                parsed = usage_from_mapping(
                    obj.get("usage") if isinstance(obj.get("usage"), dict) else None
                )
                if parsed:
                    last = parsed
    except OSError:
        return {}
    return last


def duration_s_from_run_dir(run_dir: Path) -> float | None:
    for name in ("summary.json", "result.json"):
        path = run_dir / name
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        timing = raw.get("phase_timing")
        if not isinstance(timing, dict):
            timing = (raw.get("result") or {}).get("phase_timing") if isinstance(
                raw.get("result"), dict
            ) else None
        if not isinstance(timing, dict):
            continue
        total_ms = _as_float(timing.get("total_ms"))
        if total_ms is not None:
            return total_ms / 1000.0
    return None


def collect_attempt_usage(dataset_root: Path, run_id: str) -> dict[str, Any]:
    try:
        run_dir = resolve_attempt_run_dir(dataset_root, run_id)
    except ConfigError:
        return {}
    out = usage_from_trajectory(run_dir / _TRAJECTORY)
    duration_s = duration_s_from_run_dir(run_dir)
    if duration_s is not None:
        out["duration_s"] = duration_s
    return out


def overlay_model(summary: Mapping[str, Any]) -> str:
    overlay = summary.get("job_overlay")
    if not isinstance(overlay, dict):
        return str(summary.get("model_label") or "").strip()
    profiles = overlay.get("agent_profiles")
    if not isinstance(profiles, dict):
        return str(summary.get("model_label") or "").strip()
    for raw in profiles.values():
        if not isinstance(raw, dict):
            continue
        model = raw.get("model")
        if isinstance(model, str) and model.strip():
            return model.strip()
    return str(summary.get("model_label") or "").strip()


def _run_ids(summary: Mapping[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: object) -> None:
        if raw is None:
            return
        text = str(raw).strip()
        if not text or text in seen:
            return
        seen.add(text)
        out.append(text)

    attempts = summary.get("attempts")
    if isinstance(attempts, list):
        for row in attempts:
            if isinstance(row, Mapping):
                add(row.get("run_id"))
    refs = summary.get("task_refs")
    if isinstance(refs, list):
        for ref in refs:
            if not isinstance(ref, Mapping):
                continue
            ids = ref.get("attempt_run_ids")
            if isinstance(ids, list) and ids:
                for rid in ids:
                    add(rid)
            else:
                add(ref.get("run_id"))
    return out


def aggregate_usage(
    parts: Sequence[Mapping[str, Any]],
    *,
    overlay: str,
    pin: dict[str, Any] | None,
) -> dict[str, Any] | None:
    prompt = 0
    completion = 0
    cached = 0
    cost = 0.0
    duration = 0.0
    n_tokens = 0
    n_cost = 0
    n_duration = 0
    saw_prompt = False
    saw_completion = False
    saw_cached = False
    for part in parts:
        p = _as_int(part.get("prompt_tokens"))
        c = _as_int(part.get("completion_tokens"))
        k = _as_int(part.get("cached_tokens"))
        usd = _as_float(part.get("cost_usd"))
        dur = _as_float(part.get("duration_s"))
        if p is not None or c is not None:
            n_tokens += 1
        if p is not None:
            prompt += p
            saw_prompt = True
        if c is not None:
            completion += c
            saw_completion = True
        if k is not None:
            cached += k
            saw_cached = True
        if usd is not None:
            cost += usd
            n_cost += 1
        if dur is not None:
            duration += dur
            n_duration += 1
    if not saw_prompt and not saw_completion and n_cost == 0 and n_duration == 0:
        return None
    bag: dict[str, Any] = {
        "n_attempts_with_tokens": n_tokens,
        "n_attempts_with_cost": n_cost,
    }
    if saw_prompt:
        bag["prompt_tokens"] = prompt
    if saw_completion:
        bag["completion_tokens"] = completion
    if saw_cached:
        bag["cached_tokens"] = cached
    if n_cost:
        bag["cost_usd"] = cost
    if n_duration:
        bag["duration_s"] = duration
    estimated = estimate_cost_usd(
        prompt_tokens=prompt if saw_prompt else None,
        completion_tokens=completion if saw_completion else None,
        cached_tokens=cached if saw_cached else None,
        overlay=overlay,
        pin=pin,
    )
    if estimated is not None:
        bag["cost_usd_estimated"] = estimated
    if n_cost and n_tokens and n_cost == n_tokens:
        bag["cost_source"] = "reported"
    elif estimated is not None:
        bag["cost_source"] = "estimated"
    elif n_cost:
        bag["cost_source"] = "reported"
    else:
        bag["cost_source"] = "missing"
    return bag


def collect_suite_usage(
    dataset_root: Path,
    summary: Mapping[str, Any],
) -> dict[str, Any] | None:
    parts: list[dict[str, Any]] = []
    for run_id in _run_ids(summary):
        part = collect_attempt_usage(dataset_root, run_id)
        if part:
            parts.append(part)
    if not parts:
        return None
    return aggregate_usage(
        parts,
        overlay=overlay_model(summary),
        pin=load_model_pin(),
    )


def merge_suite_usage(
    metrics: Mapping[str, Any],
    summary: Mapping[str, Any],
    dataset_root: Path,
) -> dict[str, Any]:
    """Attach ``metrics.usage`` when missing and local Attempt dirs can fill it."""
    out = dict(metrics)
    existing = out.get("usage")
    if isinstance(existing, dict) and (
        existing.get("prompt_tokens") is not None
        or existing.get("completion_tokens") is not None
        or existing.get("cost_usd") is not None
        or existing.get("cost_usd_estimated") is not None
    ):
        return out
    collected = collect_suite_usage(dataset_root, summary)
    if collected:
        out["usage"] = collected
    return out
