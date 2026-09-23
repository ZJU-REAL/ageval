"""Tabs, agent surface, and trial meta projection for viewer."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ageval.evidence.attempt_record import has_attempt_result, read_attempt_result
from ageval.evidence.identity import dataset_identity, dataset_ref
from ageval.evidence.trajectory import TRAJECTORY_FILENAME
from ageval.evidence.usage import observational_bag, terminal_extra
from ageval.viewer.jobs import _duration_label, _environment_kind, _phase_timing, _started_at
from ageval.viewer.trials.paths import _read_json_object
from ageval.viewer.trials.usage import (
    _format_latency_ms,
    _read_terminal_usage,
    _usage_summary_for_actor,
)


def _has_any_file(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_file():
        return True
    try:
        for p in path.rglob("*"):
            if p.is_file():
                return True
    except OSError:
        return False
    return False


def _available_tabs(evidence: Path) -> list[str]:
    tabs: list[str] = []
    # One trajectory per Attempt, written by the record phase.
    has_traj = (evidence / TRAJECTORY_FILENAME).is_file()
    if has_traj:
        tabs.append("trajectory")
    if (evidence / "agent").is_dir() and _has_any_file(evidence / "agent"):
        tabs.append("agent")
    if (
        _has_any_file(evidence / "evaluation")
        or _has_any_file(evidence / "eval_staging")
        or has_attempt_result(evidence)
    ):
        tabs.append("verifier")
    # Artifacts: harness publish tree or common artifact dirs
    art_candidates = [
        evidence / "harness",
        evidence / "artifacts",
        evidence / "agent" / "artifacts",
    ]
    # Prefer a dedicated tab only when files exist under artifact-ish trees
    try:
        if any(_has_any_file(p) for p in art_candidates):
            tabs.append("artifacts")
    except OSError:
        pass
    if (evidence / "lock.json").is_file():
        tabs.append("lock")
    # Runtime facts: effects / cleanup / summary (not agent trajectory, not artifacts)
    if (
        (evidence / "effects.jsonl").is_file()
        or (evidence / "cleanup.json").is_file()
        or (evidence / "summary.json").is_file()
        or (evidence / "agent.json").is_file()
        or (evidence / "harness.json").is_file()
    ):
        tabs.append("runtime")
    return tabs


_TRANSPORT_ACP = "acp"


def _nonempty_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _overlay_bindings(lock: dict[str, Any]) -> dict[str, dict[str, Any]]:
    overlay = lock.get("job_overlay")
    if not isinstance(overlay, dict):
        return {}
    bindings = overlay.get("agent_profiles")
    if not isinstance(bindings, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, raw in bindings.items():
        if isinstance(key, str) and key and isinstance(raw, dict):
            out[key] = raw
    return out


def _projected_acp_entry(profile: Mapping[str, Any] | None) -> str | None:
    """Lock summary writes ACP entry on ``options.entry``, not extensions."""
    if not isinstance(profile, Mapping):
        return None
    entry = profile.get("entry")
    if isinstance(entry, str) and entry.strip():
        return entry.strip()
    opts = profile.get("options")
    if isinstance(opts, dict):
        val = opts.get("entry")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _display_binding(
    profile: dict[str, Any],
    overlay_binding: dict[str, Any] | None,
) -> dict[str, Any]:
    """Richest binding for ``display_agent_name`` (overlay label/extensions first)."""
    src = overlay_binding or profile
    entry = _projected_acp_entry(src) or _projected_acp_entry(profile)
    if not entry or src.get("entry") == entry:
        return src
    merged = dict(src)
    merged["entry"] = entry
    return merged


def _actor_agent_name(
    profile: dict[str, Any],
    *,
    overlay_binding: dict[str, Any] | None = None,
    inv_entry: str | None = None,
) -> str:
    """Same axis as Jobs / Hub: label → ACP entry → executor. Never transport ``acp``."""
    from ageval.config.profiles import display_agent_name

    name = display_agent_name(_display_binding(profile, overlay_binding))
    if name and name != _TRANSPORT_ACP:
        return name
    if isinstance(inv_entry, str) and inv_entry.strip():
        return inv_entry.strip()
    pid = profile.get("id")
    if isinstance(pid, str) and pid.strip():
        return pid.strip()
    return ""


def _provenance_surface(lock: dict[str, Any]) -> dict[str, Any]:
    """Project lock provenance for Attempt top bar (url only when present)."""
    prov = lock.get("provenance")
    if not isinstance(prov, dict):
        return {
            "provenance": None,
            "upstream_url": None,
            "upstream_name": None,
            "upstream_ref": None,
        }
    upstream = prov.get("upstream") if isinstance(prov.get("upstream"), dict) else {}
    url = upstream.get("url") if isinstance(upstream, dict) else None
    name = upstream.get("name") if isinstance(upstream, dict) else None
    ref = upstream.get("ref") if isinstance(upstream, dict) else None
    return {
        "provenance": prov,
        "upstream_url": url if isinstance(url, str) and url.strip() else None,
        "upstream_name": name if isinstance(name, str) and name.strip() else None,
        "upstream_ref": ref if isinstance(ref, str) and ref.strip() else None,
    }


def _agent_surface(
    evidence: Path,
    *,
    lock: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic agent surface from lock profiles + invocation metadata.

    Missing optional fields stay null; never invents values. Priority:
    lock.profiles for declared rows; invocation metadata overrides model when set.

    Per-profile Time / Usage (#27): sum latency_ms; take **last** invoke usage
    (session-cumulative tokens/cost — do not sum cumulative fields).
    """
    profiles_raw = [p for p in (lock.get("profiles") or []) if isinstance(p, dict)]
    by_id: dict[str, dict[str, Any]] = {}
    for p in profiles_raw:
        pid = p.get("id")
        if isinstance(pid, str) and pid:
            by_id[pid] = p

    # Order of appearance: first from invocations (actual use), else lock order.
    ordered_ids: list[str] = []
    inv_model: dict[str, str] = {}
    inv_executor: dict[str, str] = {}
    inv_entry: dict[str, str] = {}
    inv_effort: dict[str, str] = {}
    # Aggregation state per profile_id
    latency_sum: dict[str, float] = {}
    invoke_count: dict[str, int] = {}
    last_usage: dict[str, dict[str, Any]] = {}
    overlay_by_id = _overlay_bindings(lock)
    from ageval.config.profiles import effective_profile, reasoning_effort_from_profile

    inv_root = evidence / "agent" / "invocations"
    if inv_root.is_dir():
        try:
            inv_dirs = sorted(p for p in inv_root.iterdir() if p.is_dir())
        except OSError:
            inv_dirs = []
        for inv in inv_dirs:
            meta = _read_json_object(inv / "metadata.json") or {}
            pid = meta.get("profile_id")
            if isinstance(pid, str) and pid:
                if pid not in ordered_ids:
                    ordered_ids.append(pid)
                mid = meta.get("model")
                if isinstance(mid, str) and mid:
                    inv_model[pid] = mid
                ek = meta.get("executor_kind")
                if isinstance(ek, str) and ek:
                    inv_executor[pid] = ek
                acp_entry = meta.get("acp_entry_id")
                if isinstance(acp_entry, str) and acp_entry.strip():
                    inv_entry[pid] = acp_entry.strip()
                for key in ("actual_reasoning_effort", "locked_reasoning_effort"):
                    val = meta.get(key)
                    if isinstance(val, str) and val.strip():
                        inv_effort[pid] = val.strip()
                        break
                invoke_count[pid] = invoke_count.get(pid, 0) + 1
                lat = meta.get("latency_ms")
                if isinstance(lat, (int, float)) and not isinstance(lat, bool):
                    latency_sum[pid] = latency_sum.get(pid, 0.0) + float(lat)
                session = meta.get("session_id")
                usage = _read_terminal_usage(
                    evidence / TRAJECTORY_FILENAME,
                    session_id=str(session) if isinstance(session, str) and session else None,
                )
                if usage is not None:
                    # Last invoke wins (session cumulative semantics).
                    last_usage[pid] = usage
    jsonl_latency, jsonl_count, jsonl_usage, jsonl_extra = _usage_time_from_trajectory(
        evidence / TRAJECTORY_FILENAME
    )
    for pid, usage in jsonl_usage.items():
        last_usage[pid] = usage
        if pid not in ordered_ids:
            ordered_ids.append(pid)
    if not ordered_ids:
        ordered_ids = [pid for pid in by_id]

    actors: list[dict[str, Any]] = []
    executors: list[str] = []
    for pid in ordered_ids:
        p = by_id.get(pid, {"id": pid})
        overlay = effective_profile(overlay_by_id, pid)
        ex = (
            _nonempty_str(p.get("executor"))
            or inv_executor.get(pid)
            or _nonempty_str((overlay or {}).get("executor"))
        )
        if isinstance(ex, str) and ex and ex not in executors:
            executors.append(ex)
        # Invocation (actual) → lock profiles → sealed job_overlay.
        # Evidence lock.json is often overlay-only; vendor metadata.json is
        # dropped by default, so overlay is the declared model for this run.
        model = (
            inv_model.get(pid)
            or _nonempty_str(p.get("model"))
            or _nonempty_str((overlay or {}).get("model"))
        )
        effort = (
            inv_effort.get(pid)
            or reasoning_effort_from_profile(overlay)
            or reasoning_effort_from_profile(p)
            or None
        )
        agent_col = (
            _actor_agent_name(
                p,
                overlay_binding=overlay,
                inv_entry=inv_entry.get(pid),
            )
            or pid
        )
        role_col = pid
        n_inv = jsonl_count.get(pid) or invoke_count.get(pid, 0)
        lat_total = jsonl_latency.get(pid)
        if lat_total is None:
            lat_total = latency_sum.get(pid)
        usage_summary = _usage_summary_for_actor(last_usage.get(pid), jsonl_extra.get(pid))
        actors.append(
            {
                "role": role_col,
                "agent": agent_col,
                "model": model,
                "reasoning_effort": effort,
                "profile_id": pid,
                # Surface executor mechanism on actor rows (nooa/acp/…).
                "executor_kind": ex,
                "invokes": n_inv,
                "latency_ms_sum": lat_total,
                "time_label": _format_latency_ms(lat_total, n_inv),
                "usage": usage_summary,
                "usage_label": (
                    usage_summary.get("label") if isinstance(usage_summary, dict) else None
                ),
            }
        )

    framework = executors[0] if executors else None
    prov = _provenance_surface(lock)

    return {
        "framework": framework,
        "actors": actors,
        # Keep thin aliases for older clients / tests
        "agent_label": actors[0]["role"] if len(actors) == 1 else None,
        "model_label": actors[0]["model"] if len(actors) == 1 else None,
        "executor_kind": executors[0] if executors else None,
        "profiles": actors,
        "provenance": prov.get("provenance"),
        "upstream_url": prov.get("upstream_url"),
        "upstream_name": prov.get("upstream_name"),
        "upstream_ref": prov.get("upstream_ref"),
    }


def _trial_meta_from_evidence(
    evidence: Path,
    *,
    run_id: str,
    task_id: str | None,
    suite_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = read_attempt_result(evidence) or {}
    summary = _read_json_object(evidence / "summary.json") or {}
    lock = _read_json_object(evidence / "lock.json") or {}
    suite_row = suite_row or {}

    status = suite_row.get("status") or result.get("status") or summary.get("status") or None
    if isinstance(status, str):
        status = status.upper()
    score = suite_row.get("score")
    if score is None:
        score = result.get("score")
    if score is None:
        score = summary.get("score")
    nested = summary.get("result") if isinstance(summary.get("result"), dict) else {}
    error = (
        suite_row.get("error") or result.get("error") or nested.get("error") or summary.get("error")
    )
    limit = suite_row.get("limit")
    if limit is None:
        limit = result.get("limit")
    if limit is None:
        limit = nested.get("limit")
    if limit is None:
        limit = summary.get("limit")
    locked_task = lock.get("task_id") if isinstance(lock.get("task_id"), str) else None
    surface = _agent_surface(evidence, lock=lock)
    did, ver = dataset_identity(lock, location=str(evidence / "lock.json"))
    ref = dataset_ref(did, ver)

    phase_timing = _phase_timing(summary) or _phase_timing(suite_row)
    duration = _duration_label(phase_timing)
    started = _started_at(phase_timing)

    # Token breakdown from actors (observational; Harbor-style bar when present).
    token_timing = _token_bar_from_actors(surface.get("actors") or [])

    return {
        "trial_id": run_id,
        "run_id": run_id,
        "task_id": task_id or locked_task or suite_row.get("task_id"),
        "status": status,
        "score": score,
        "reward": score,
        "error": error,
        "limit": limit,
        "exit_code": suite_row.get("exit_code") or result.get("exit_code"),
        "duration": duration,
        "started": started,
        "phase_timing": phase_timing,
        "token_timing": token_timing,
        "evidence_relpath": None,  # filled by caller
        "has_evidence": True,
        "available_tabs": _available_tabs(evidence),
        "agent_invocations": result.get("agent_invocations") or summary.get("agent_invocations"),
        "harness_kind": result.get("harness_kind") or summary.get("harness_kind"),
        "framework": surface.get("framework"),
        "environment": _environment_kind(lock, result),
        "actors": surface.get("actors") or [],
        "agent_label": surface.get("agent_label"),
        "model_label": surface.get("model_label"),
        "executor_kind": surface.get("executor_kind"),
        "profiles": surface.get("profiles") or [],
        "provenance": surface.get("provenance"),
        "upstream_url": surface.get("upstream_url"),
        "upstream_name": surface.get("upstream_name"),
        "upstream_ref": surface.get("upstream_ref"),
        "note": None,
        "extra": observational_bag(summary.get("extra")),
        "dataset_id": did,
        "dataset_version": ver,
        "dataset_ref": ref,
    }


def _usage_time_from_trajectory(
    traj_path: Path,
) -> tuple[dict[str, float], dict[str, int], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Last usage/extra + summed elapsed per profile_id from layer C terminals.

    Labels come from ``terminal.metadata.profile_id`` so slim archives without
    invocation ``metadata.json`` still paint Time / Usage. Observational.
    """
    latency: dict[str, float] = {}
    count: dict[str, int] = {}
    last_usage: dict[str, dict[str, Any]] = {}
    last_extra: dict[str, dict[str, Any]] = {}
    if not traj_path.is_file():
        return latency, count, last_usage, last_extra
    try:
        with traj_path.open("r", encoding="utf-8", errors="replace") as fh:
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
                meta_raw = obj.get("metadata")
                meta: dict[str, Any] = dict(meta_raw) if isinstance(meta_raw, dict) else {}
                pid = meta.get("profile_id")
                if not isinstance(pid, str) or not pid:
                    continue
                usage = obj.get("usage")
                if isinstance(usage, dict) and usage:
                    last_usage[pid] = usage
                extra = terminal_extra(obj)
                if extra:
                    last_extra[pid] = extra
                elapsed = obj.get("elapsed_ms")
                if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool):
                    elapsed = meta.get("latency_ms")
                if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool):
                    latency[pid] = latency.get(pid, 0.0) + float(elapsed)
                    count[pid] = count.get(pid, 0) + 1
    except OSError:
        return latency, count, last_usage, last_extra
    return latency, count, last_usage, last_extra


def _token_bar_from_actors(actors: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Aggregate last-invoke token fields across actors for a Harbor-like token bar."""
    cached = 0.0
    uncached = 0.0
    output = 0.0
    any_tok = False
    for a in actors:
        if not isinstance(a, dict):
            continue
        usage = a.get("usage")
        if not isinstance(usage, dict):
            continue
        inp = usage.get("input_tokens")
        out = usage.get("output_tokens")
        cached_read = usage.get("cached_read_tokens")
        if isinstance(out, (int, float)) and not isinstance(out, bool):
            output += float(out)
            any_tok = True
        if isinstance(inp, (int, float)) and not isinstance(inp, bool):
            any_tok = True
            cr = (
                float(cached_read)
                if isinstance(cached_read, (int, float)) and not isinstance(cached_read, bool)
                else 0.0
            )
            cached += cr
            uncached += max(0.0, float(inp) - cr)
        elif isinstance(cached_read, (int, float)) and not isinstance(cached_read, bool):
            cached += float(cached_read)
            any_tok = True
    if not any_tok:
        return None
    segments = [
        {"id": "cached_input", "label": "Cached Input", "tokens": int(round(cached))},
        {"id": "uncached_input", "label": "Uncached Input", "tokens": int(round(uncached))},
        {"id": "output", "label": "Output", "tokens": int(round(output))},
    ]
    total = sum(s["tokens"] for s in segments)
    return {"schema": "ageval.token_timing/1", "segments": segments, "total_tokens": total}
