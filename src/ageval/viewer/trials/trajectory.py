"""Trajectory read APIs for viewer trials (observational, not PASS)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ageval.evidence.locators import safe_id_segment
from ageval.evidence.trajectory import OBSERVATION_REL, TRAJECTORY_FILENAME
from ageval.evidence.usage import terminal_extra
from ageval.viewer.jobs import get_job
from ageval.viewer.trials.constants import MAX_JSONL_LINE, MAX_TRAJECTORY_STEPS
from ageval.viewer.trials.paths import (
    _read_json_object,
    _safe_run_id,
    resolve_evidence_root,
)


def trial_trajectory(
    dataset_root: Path,
    job_id: str,
    task_id: str,
    run_id: str,
) -> dict[str, Any]:
    root = dataset_root.expanduser().resolve(strict=False)
    safe_id_segment(job_id, field="job_id")
    task_id = safe_id_segment(task_id, field="task_id")
    rid = _safe_run_id(run_id)
    get_job(root, job_id)
    evidence = resolve_evidence_root(root, rid, task_id=task_id, require_task_match=True)
    # One trajectory per Attempt, written by the record phase. The invocation
    # directories still hold the per-call metadata, so the rows are labelled
    # from them by session.
    steps: list[dict[str, Any]] = []
    invocations: list[dict[str, Any]] = []
    truncated = False

    rows = _parse_trajectory_jsonl(evidence / TRAJECTORY_FILENAME)
    truncated = len(rows) >= MAX_TRAJECTORY_STEPS
    by_session: dict[str, dict[str, Any]] = {}
    inv_root = evidence / "agent" / "invocations"
    if inv_root.is_dir():
        for inv in sorted((p for p in inv_root.iterdir() if p.is_dir()), key=lambda p: p.name):
            meta = _read_json_object(inv / "metadata.json") or {}
            row = {
                "dirname": inv.name,
                "invocation_id": meta.get("invocation_id") or inv.name,
                "profile_id": meta.get("profile_id"),
                "executor_kind": meta.get("executor_kind"),
                "model": meta.get("model") or meta.get("locked_model"),
                "status": meta.get("status"),
                "latency_ms": meta.get("latency_ms"),
                "session_id": meta.get("session_id"),
                "step_count": 0,
            }
            invocations.append(row)
            session = str(meta.get("session_id") or "")
            if session:
                by_session[session] = row

    for entry in rows:
        meta_raw = entry.get("metadata")
        row_meta: dict[str, Any] = dict(meta_raw) if isinstance(meta_raw, dict) else {}
        label = by_session.get(str(entry.get("session_id") or "")) or (
            invocations[0] if len(invocations) == 1 else None
        )
        if label is not None:
            label["step_count"] = int(label["step_count"]) + 1
        parsed_pid = entry.get("profile_id") if isinstance(entry.get("profile_id"), str) else None
        meta_pid = (
            row_meta.get("profile_id") if isinstance(row_meta.get("profile_id"), str) else None
        )
        profile_id = parsed_pid or meta_pid or (label or {}).get("profile_id")
        model = row_meta.get("model") if isinstance(row_meta.get("model"), str) else None
        elapsed = entry.get("elapsed_ms")
        if elapsed is None:
            lat = row_meta.get("latency_ms")
            if isinstance(lat, (int, float)) and not isinstance(lat, bool):
                elapsed = lat
        steps.append(
            {
                **entry,
                "elapsed_ms": elapsed,
                "invocation": (label or {}).get("dirname"),
                "invocation_id": row_meta.get("invocation_id")
                or (label or {}).get("invocation_id"),
                "profile_id": profile_id,
                "model": model or (label or {}).get("model"),
            }
        )

    _backfill_profile_ids(steps)
    return {
        "ok": True,
        "run_id": rid,
        "task_id": task_id,
        "steps": steps,
        "step_count": len(steps),
        "invocations": invocations,
        "truncated": truncated,
        "note": None,
    }


def trial_evaluation_observation(
    dataset_root: Path,
    job_id: str,
    task_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Verifier steps from ``evaluation/observation.jsonl``. Missing file → no steps."""
    root = dataset_root.expanduser().resolve(strict=False)
    safe_id_segment(job_id, field="job_id")
    task_id = safe_id_segment(task_id, field="task_id")
    rid = _safe_run_id(run_id)
    get_job(root, job_id)
    evidence = resolve_evidence_root(root, rid, task_id=task_id, require_task_match=True)
    path = evidence / OBSERVATION_REL
    rows = _parse_trajectory_jsonl(path) if path.is_file() else []
    truncated = len(rows) >= MAX_TRAJECTORY_STEPS
    steps: list[dict[str, Any]] = []
    for entry in rows:
        meta_raw = entry.get("metadata")
        row_meta: dict[str, Any] = dict(meta_raw) if isinstance(meta_raw, dict) else {}
        parsed_pid = entry.get("profile_id") if isinstance(entry.get("profile_id"), str) else None
        meta_pid = (
            row_meta.get("profile_id") if isinstance(row_meta.get("profile_id"), str) else None
        )
        elapsed = entry.get("elapsed_ms")
        if elapsed is None:
            lat = row_meta.get("latency_ms")
            if isinstance(lat, (int, float)) and not isinstance(lat, bool):
                elapsed = lat
        steps.append(
            {
                **entry,
                "elapsed_ms": elapsed,
                "profile_id": parsed_pid or meta_pid,
                "model": row_meta.get("model") if isinstance(row_meta.get("model"), str) else None,
            }
        )
    _backfill_profile_ids(steps)
    return {
        "ok": True,
        "run_id": rid,
        "task_id": task_id,
        "steps": steps,
        "step_count": len(steps),
        "invocations": [],
        "truncated": truncated,
        "note": None,
    }


def _parse_trajectory_jsonl(path: Path) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line_no, line in enumerate(fh, start=1):
                if len(steps) >= MAX_TRAJECTORY_STEPS:
                    break
                raw = line.strip()
                if not raw:
                    continue
                if len(raw) > MAX_JSONL_LINE:
                    raw = raw[:MAX_JSONL_LINE]
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    steps.append(
                        {
                            "type": "parse_error",
                            "line": line_no,
                            "content": raw[:500],
                        }
                    )
                    continue
                if not isinstance(obj, dict):
                    steps.append({"type": "raw", "line": line_no, "content": str(obj)[:500]})
                    continue
                role = obj.get("role")
                step_type = obj.get("type") or ("turn" if role else "event")
                content = obj.get("content")
                if content is not None and not isinstance(content, str):
                    try:
                        content = json.dumps(content, ensure_ascii=False)
                    except (TypeError, ValueError):
                        content = str(content)
                if isinstance(content, str) and len(content) > 8_000:
                    content = content[:8_000] + "…[truncated]"

                # tool_call / observation: surface args & raw_output as content when needed
                args = obj.get("args")
                raw_output = obj.get("raw_output")
                if step_type == "tool_call" and content is None and args is not None:
                    try:
                        content = json.dumps(args, ensure_ascii=False)
                    except (TypeError, ValueError):
                        content = str(args)
                    if isinstance(content, str) and len(content) > 8_000:
                        content = content[:8_000] + "…[truncated]"
                if step_type == "observation" and content is None and raw_output is not None:
                    try:
                        content = json.dumps(raw_output, ensure_ascii=False)
                    except (TypeError, ValueError):
                        content = str(raw_output)
                    if isinstance(content, str) and len(content) > 8_000:
                        content = content[:8_000] + "…[truncated]"

                # permission_decision: decision summary (no tool payload secrets)
                if step_type == "permission_decision" and content is None:
                    parts: list[str] = []
                    for key in ("policy", "outcome", "option_id"):
                        val = obj.get(key)
                        if val is not None and val != "":
                            parts.append(f"{key}={val}")
                    if parts:
                        content = " · ".join(parts)

                # terminal: ageval invoke footer (ok / stop / usage / entry meta)
                if step_type == "terminal" and content is None:
                    tparts: list[str] = []
                    if obj.get("ok") is True:
                        tparts.append("ok")
                    elif obj.get("ok") is False:
                        tparts.append("not ok")
                    stop = obj.get("stop_reason")
                    if isinstance(stop, str) and stop:
                        tparts.append(f"stop={stop}")
                    err = obj.get("error")
                    if err is not None and err != "":
                        tparts.append(f"error={err}")
                    # Usage chips live on the SPA TERMINAL card; do not dump
                    # the object into the body text.
                    meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else None
                    if meta:
                        # Compact interesting keys only
                        bits = []
                        for k in (
                            "executor_kind",
                            "acp_entry_id",
                            "actual_model",
                            "locked_model",
                            "protocol_version",
                        ):
                            if k in meta and meta[k] is not None:
                                bits.append(f"{k}={meta[k]}")
                        if bits:
                            tparts.append(" ".join(bits))
                    if tparts:
                        content = " · ".join(tparts)
                        if len(content) > 8_000:
                            content = content[:8_000] + "…[truncated]"

                steps.append(
                    {
                        "type": step_type,
                        "role": role,
                        "part": obj.get("part") if isinstance(obj.get("part"), str) else None,
                        "content": content,
                        "turn_index": obj.get("turn_index"),
                        "session_id": obj.get("session_id"),
                        "profile_id": (
                            obj.get("profile_id")
                            if isinstance(obj.get("profile_id"), str)
                            else None
                        ),
                        "source": obj.get("source"),
                        "stop_reason": obj.get("stop_reason"),
                        "ok": obj.get("ok"),
                        "error": obj.get("error"),
                        "usage": obj.get("usage") if isinstance(obj.get("usage"), dict) else None,
                        "extra": terminal_extra(obj),
                        "metadata": obj.get("metadata")
                        if isinstance(obj.get("metadata"), dict)
                        else None,
                        # tool_call / observation fields (fail-open; unknown types ignore)
                        "tool_call_id": obj.get("tool_call_id"),
                        "title": obj.get("title"),
                        "function_name": obj.get("function_name"),
                        "kind": obj.get("kind"),
                        "status": obj.get("status"),
                        "args": args if isinstance(args, (dict, list, str)) else None,
                        "raw_output": raw_output
                        if isinstance(raw_output, (dict, list, str))
                        else None,
                        "elapsed_ms": (
                            obj.get("elapsed_ms")
                            if isinstance(obj.get("elapsed_ms"), (int, float))
                            and not isinstance(obj.get("elapsed_ms"), bool)
                            else None
                        ),
                        "started_at": obj.get("started_at")
                        if isinstance(obj.get("started_at"), str)
                        else None,
                        "ended_at": obj.get("ended_at")
                        if isinstance(obj.get("ended_at"), str)
                        else None,
                        # permission_decision summary fields
                        "outcome": obj.get("outcome"),
                        "option_id": obj.get("option_id"),
                        "policy": obj.get("policy"),
                        "line": line_no,
                    }
                )
    except OSError:
        return steps
    return steps


def _backfill_profile_ids(steps: list[dict[str, Any]]) -> None:
    """Copy package-role profile_id onto rows that only the terminal carried.

    Old sealed jsonl stamped profile_id on ``terminal.metadata`` only. Same
    ``turn_index`` is one invoke; later rows in that turn (the terminal) win.
    """
    by_turn: dict[int, str] = {}
    for step in steps:
        ti = step.get("turn_index")
        if not isinstance(ti, int):
            continue
        pid = step.get("profile_id")
        if not isinstance(pid, str) or not pid:
            meta = step.get("metadata")
            raw = meta.get("profile_id") if isinstance(meta, dict) else None
            pid = raw if isinstance(raw, str) and raw else None
        if isinstance(pid, str) and pid:
            by_turn[ti] = pid
    for step in steps:
        existing = step.get("profile_id")
        if isinstance(existing, str) and existing:
            continue
        ti = step.get("turn_index")
        pid = by_turn.get(ti) if isinstance(ti, int) else None
        if pid:
            step["profile_id"] = pid
