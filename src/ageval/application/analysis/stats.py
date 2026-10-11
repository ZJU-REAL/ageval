"""Deterministic trajectory stats. Observational — never PASS."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ageval.application.analysis.read import attempt_status, read_json_object, read_trajectory

_FAILURE_STATUS = frozenset({"error", "failed", "failure", "cancelled", "canceled", "timeout"})
_EXIT_CODE = re.compile(r"exit_code[\"'\s:=]+(-?\d+)", re.IGNORECASE)


def build_stats(run_dir: Path, *, run_id: str, task_id: str | None) -> dict[str, Any]:
    rows = read_trajectory(run_dir)
    summary = read_json_object(run_dir / "summary.json")
    calls = [row for row in rows if row.get("type") == "tool_call"]
    observations = _observations_by_id(rows)
    failures = 0
    codes: Counter[str] = Counter()
    for call in calls:
        obs = observations.get(str(call.get("tool_call_id") or ""))
        if not _tool_failed(call, obs):
            continue
        failures += 1
        codes[_failure_code(call, obs)] += 1
    for row in rows:
        if row.get("type") != "terminal":
            continue
        if row.get("ok") is True:
            continue
        err = row.get("error")
        if isinstance(err, str) and err.strip():
            codes[err.strip()] += 1
    _phase_failed_codes(summary, codes)
    timing, stall_count, gaps = _summary_metrics(summary)
    tool_count = len(calls)
    rate = round(failures / tool_count, 4) if tool_count else None
    body: dict[str, Any] = {
        "run_id": run_id,
        "attempt_status": attempt_status(run_dir),
        "metrics": {
            "invoke_count": sum(1 for row in rows if row.get("type") == "terminal"),
            "tool_call_count": tool_count,
            "tool_failure_count": failures,
            "tool_failure_rate": rate,
            "phase_timing": timing,
            "upstream_stall_count": stall_count,
            "repeated_tool_calls": _repeated(calls),
            "error_codes": dict(sorted(codes.items())),
            "gaps": gaps,
        },
    }
    if task_id:
        body["task_id"] = task_id
    return body


def _observations_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("type") != "observation":
            continue
        call_id = row.get("tool_call_id")
        if isinstance(call_id, str) and call_id:
            found[call_id] = row
    return found


def _tool_failed(call: dict[str, Any], obs: dict[str, Any] | None) -> bool:
    if _status_failed(call.get("status")):
        return True
    if obs is None:
        return False
    if _status_failed(obs.get("status")):
        return True
    return _nonzero_exit(_blob(obs)) is not None


def _failure_code(call: dict[str, Any], obs: dict[str, Any] | None) -> str:
    blob = _blob(call)
    if obs is not None:
        blob = f"{blob}\n{_blob(obs)}"
    exit_code = _nonzero_exit(blob)
    if exit_code is not None:
        return f"exit_{exit_code}"
    for source in (obs, call):
        if not isinstance(source, dict):
            continue
        for key in ("error_code", "error"):
            val = source.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        status = source.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip().lower()
    return "tool_failure"


def _status_failed(raw: object) -> bool:
    return isinstance(raw, str) and raw.strip().lower() in _FAILURE_STATUS


def _nonzero_exit(text: str) -> str | None:
    match = _EXIT_CODE.search(text)
    if match is None or match.group(1) in {"0", "+0", "-0"}:
        return None
    return match.group(1)


def _blob(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("content", "title", "function_name", "status", "error", "error_code", "raw_output"):
        val = row.get(key)
        if isinstance(val, str):
            parts.append(val)
        elif val is not None:
            parts.append(json.dumps(val, ensure_ascii=False, default=str))
    args = row.get("args")
    if args is not None:
        parts.append(json.dumps(args, ensure_ascii=False, sort_keys=True, default=str))
    return "\n".join(parts)


def _repeated(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for call in calls:
        name = str(call.get("function_name") or "tool")
        args = call.get("args")
        key = name + "\n" + json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
        slot = groups.get(key)
        if slot is None:
            groups[key] = {"function_name": name, "args": args, "count": 1}
        else:
            slot["count"] = int(slot["count"]) + 1
    repeated = [row for row in groups.values() if int(row["count"]) >= 2]
    repeated.sort(key=lambda row: (-int(row["count"]), str(row["function_name"])))
    return repeated[:20]


def _phase_failed_codes(summary: dict[str, Any] | None, codes: Counter[str]) -> None:
    if not isinstance(summary, dict):
        return
    facts = summary.get("facts")
    if not isinstance(facts, list):
        return
    for fact in facts:
        if not isinstance(fact, dict) or fact.get("name") != "phase_failed":
            continue
        detail = fact.get("detail")
        title = detail.get("title") if isinstance(detail, dict) else None
        if isinstance(title, str) and title.strip():
            codes[title.strip()] += 1


def _summary_metrics(
    summary: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, int | None, list[str]]:
    gaps: list[str] = []
    if not isinstance(summary, dict):
        return None, None, ["phase_timing", "upstream_stall_count"]
    timing = summary.get("phase_timing")
    phase_timing = timing if isinstance(timing, dict) else None
    if phase_timing is None:
        gaps.append("phase_timing")
    facts = summary.get("facts")
    if not isinstance(facts, list):
        gaps.append("upstream_stall_count")
        return phase_timing, None, gaps
    stalls = sum(
        1 for fact in facts if isinstance(fact, dict) and fact.get("name") == "upstream_stall"
    )
    return phase_timing, stalls, gaps
