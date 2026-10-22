"""On-disk jobs table: suite rows plus unclaimed single Attempts.

The single source for ``ageval jobs list``, ``GET /api/jobs`` and the Viewer
forwarding layer: how a job row is assembled from ``summary.json`` /
``progress.json`` / Attempt evidence, and which rows the table covers.
Reading a suite summary goes through ``application.suite.document``.
"""

from __future__ import annotations

import contextlib
import json
import re
from datetime import datetime
from functools import cmp_to_key
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from ageval.application.phase_timing import format_duration_ms
from ageval.application.suite import document as suite_document
from ageval.application.suite.suite_metrics import attempt_started_at
from ageval.config.dataset import load_dataset_manifest
from ageval.config.errors import ConfigError
from ageval.evidence.identity import dataset_identity, dataset_ref
from ageval.evidence.locators import (
    default_runs_root,
    default_suite_runs_root,
    resolve_attempt_run_dir,
    resolve_evidence_root,
    safe_id_segment,
)


def commands_for(root: Path, *, task_id: str | None = None) -> dict[str, str]:
    """Copyable CLI strings matching the current public surface."""
    # Prefer relative path when under cwd for nicer copy-paste.
    try:
        display = str(root.relative_to(Path.cwd()))
    except ValueError:
        display = str(root)

    harbor_kind = _harbor_kind(root)
    layout = " --layout harbor" if harbor_kind else ""
    if harbor_kind == "task":
        # A single Harbor directory rejects --task. The suite still locks by name.
        return {
            "tasks": f"ageval tasks {display}{layout}",
            "run_suite": f"ageval run {display}{layout}",
            "lock_suite_hint": f"ageval lock {display}{layout}",
        }

    cmds: dict[str, str] = {
        "tasks": f"ageval tasks {display}{layout}",
        "run_suite": f"ageval run {display}{layout}",
        "lock_suite_hint": f"ageval lock {display}{layout} --task <task_id>",
    }
    if task_id:
        cmds["run_task"] = f"ageval run {display}{layout} --task {task_id}"
        cmds["lock_task"] = f"ageval lock {display}{layout} --task {task_id}"
    return cmds


def _harbor_kind(root: Path) -> str | None:
    """``task`` or ``task-set`` when view can open this directory as Harbor."""
    from ageval.config.harbor_layout import open_harbor_root

    try:
        return open_harbor_root(root).kind
    except ConfigError:
        return None


def _suite_root(dataset_root: Path) -> Path:
    return default_suite_runs_root(dataset_root.expanduser().resolve(strict=False))


def _load_summary(path: Path) -> dict[str, Any]:
    return suite_document.load_summary_file(
        path, missing_code="invalid_package", invalid_code="invalid_package"
    )


def _task_dicts(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return suite_document.task_rows(summary)


def _ensure_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    return suite_document.metrics_and_refs(summary)[0]


def _ensure_task_refs(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return suite_document.metrics_and_refs(summary)[1]


def _attempt_dicts(summary: dict[str, Any]) -> list[dict[str, Any]]:
    raw = summary.get("attempts")
    if not isinstance(raw, list):
        return []
    return [a for a in raw if isinstance(a, dict)]


def _attempts_for_task(summary: dict[str, Any], task_id: str) -> list[dict[str, Any]]:
    """This job's attempts for *task_id* (not other suite/single runs of the same task)."""
    rows = [
        a
        for a in _attempt_dicts(summary)
        if str(a.get("task_id") or "") == task_id and a.get("run_id")
    ]
    if rows:
        return rows
    for ref in _ensure_task_refs(summary):
        if str(ref.get("task_id") or "") != task_id:
            continue
        ids = ref.get("attempt_run_ids")
        if isinstance(ids, list) and ids:
            pointed = str(ref.get("run_id") or "").strip()
            return [
                {
                    "task_id": task_id,
                    "run_id": str(rid).strip(),
                    "status": ref.get("status"),
                    "score": ref.get("score"),
                    "error": ref.get("error") if str(rid).strip() == pointed else None,
                    "limit": ref.get("limit") if str(rid).strip() == pointed else None,
                }
                for rid in ids
                if rid is not None and str(rid).strip()
            ]
        rid = str(ref.get("run_id") or "").strip()
        if rid:
            return [
                {
                    "task_id": task_id,
                    "run_id": rid,
                    "status": ref.get("status"),
                    "score": ref.get("score"),
                    "error": ref.get("error"),
                    "limit": ref.get("limit"),
                }
            ]
    return []


def _started_from_run_dir(dataset_root: Path, run_id: str) -> str | None:
    try:
        rid = safe_id_segment(run_id, field="run_id")
        evidence = resolve_evidence_root(dataset_root, rid, require_task_match=False)
    except ConfigError:
        return None
    for name in ("summary.json", "result.json"):
        path = evidence / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(data, dict):
            started = attempt_started_at(data)
            if started:
                return started
    return None


def _previous_entries(
    ref: dict[str, Any],
    attempt_rows: list[dict[str, Any]],
    *,
    dataset_root: Path | None = None,
) -> list[dict[str, Any]]:
    raw = ref.get("previous")
    items: list[dict[str, Any]]
    if isinstance(raw, list) and raw:
        items = [dict(item) for item in raw if isinstance(item, dict)]
    else:
        items = []
        for row in attempt_rows:
            nested = row.get("previous")
            if not isinstance(nested, list):
                continue
            for item in nested:
                if isinstance(item, dict):
                    items.append(dict(item))
    if dataset_root is None:
        return items
    for item in items:
        if item.get("started_at"):
            continue
        rid = str(item.get("run_id") or "").strip()
        if not rid:
            continue
        started = _started_from_run_dir(dataset_root, rid)
        if started:
            item["started_at"] = started
    return items


def _planned_pending_rows(
    progress: dict[str, Any] | None, settled_ids: set[str]
) -> list[dict[str, Any]]:
    """Placeholder rows for planned task ids that have not settled yet.

    The suite summary deliberately contains settled tasks only; the viewer
    joins the planned axis from ``progress.json`` so the job detail page can
    show how many tasks are still to run. Placeholders carry no attempt and
    navigate nowhere.
    """
    if not isinstance(progress, dict):
        return []
    raw = progress.get("task_ids")
    if not isinstance(raw, list):
        return []
    running_ids = {
        str(item.get("task_id") or "")
        for item in progress.get("running", [])
        if isinstance(item, dict)
    }
    rows: list[dict[str, Any]] = []
    for tid in raw:
        tid = str(tid or "").strip()
        if not tid or tid in settled_ids:
            continue
        rows.append(
            {
                "task_id": tid,
                "status": "RUNNING" if tid in running_ids else "PENDING",
                "score": None,
                "run_id": None,
                "attempt_run_ids": [],
                "previous": [],
                "attempts": [],
                "error": None,
                "limit": None,
                "exit_code": None,
                "n": None,
                "c": None,
            }
        )
    return rows


def _in_progress_suite_row(
    progress: dict[str, Any],
    *,
    suite_dir: Path,
    dataset_root: Path,
    manifest: Any = None,
) -> dict[str, Any]:
    """Suite that has progress.json but no summary yet — still running."""
    del dataset_root, manifest
    sid = str(progress.get("suite_run_id") or suite_dir.name)
    total = int(progress.get("total") or 0)
    done = int(progress.get("done") or 0)
    did, ver = dataset_identity(progress, location=str(suite_dir / "progress.json"))
    ref = dataset_ref(did, ver)
    return {
        "job_id": sid,
        "job_name": sid,
        "source_kind": "suite",
        "source": did,
        "dataset_id": did,
        "dataset_version": ver,
        "dataset_ref": ref,
        "agent_label": "",
        "model_label": "",
        "reasoning_effort": "",
        "provider_label": "",
        "environment": None,
        "result": None,
        "pass_rate": None,
        "mean_score": None,
        "metrics": {"n_tasks": total, "n_pass": 0, "n_fail": 0, "n_error": 0},
        "started": progress.get("updated_at"),
        "duration": None,
        "n_attempts": progress.get("n_attempts"),
        "trials_done": done,
        "trials_total": total,
        "exit_code": None,
        "task_count": total,
        "summary_path": str(suite_dir / "progress.json"),
        "progress": progress,
        "status": str(progress.get("status") or "running"),
        "note": "suite in progress",
    }


def _chart_task_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trial squares for the suite waffle. No overlay, no error text."""
    out: list[dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        task_id = str(ref.get("task_id") or "").strip()
        if not task_id:
            continue
        row: dict[str, Any] = {"task_id": task_id}
        for key in ("status", "score", "run_id", "n", "c", "attempt_run_ids"):
            if key in ref:
                row[key] = ref[key]
        previous = ref.get("previous")
        if isinstance(previous, list):
            prev_out: list[dict[str, Any]] = []
            for item in previous:
                if not isinstance(item, dict):
                    continue
                prev = {
                    key: item[key]
                    for key in ("run_id", "status", "score", "attempt_index")
                    if key in item
                }
                if prev:
                    prev_out.append(prev)
            if prev_out:
                row["previous"] = prev_out
        run_ids = [str(row.get("run_id") or "").strip()]
        extra = row.get("attempt_run_ids")
        if isinstance(extra, list):
            run_ids.extend(str(item or "").strip() for item in extra)
        if any(run_ids):
            row["has_attempt_content"] = True
        out.append(row)
    return out


def _job_row(
    summary: dict[str, Any],
    *,
    suite_dir: Path,
    dataset_root: Path,
    manifest: Any = None,
) -> dict[str, Any]:
    metrics, refs = suite_document.metrics_and_refs(summary)
    n_tasks = int(metrics.get("n_tasks") or len(refs) or 0)
    n_done = int(metrics.get("n_pass") or 0) + int(metrics.get("n_fail") or 0)
    # Trials fraction: completed / planned
    trials_done = (
        n_done
        if n_done
        else int(metrics.get("n_pass") or 0)
        + int(metrics.get("n_fail") or 0)
        + int(metrics.get("n_error") or 0)
    )
    if trials_done == 0 and n_tasks:
        trials_done = n_tasks  # full suite summary usually has all rows
        # Prefer counting actual refs
        trials_done = len(refs) if refs else n_tasks

    overlay = _overlay_from_job_summary(summary, dataset_root=dataset_root)
    from ageval.config.overlay_files import overlay_paths_from_job_overlay
    from ageval.config.profiles import display_labels_from_overlay

    agent_label, model_label = display_labels_from_overlay(overlay)
    if not agent_label:
        agent_label = str(summary.get("agent_label") or "")
    if not model_label:
        model_label = str(summary.get("model_label") or "")

    did, ver = dataset_identity(summary, location=str(suite_dir / "summary.json"))
    ref = dataset_ref(did, ver)
    row = {
        "job_id": str(summary.get("suite_run_id") or suite_dir.name),
        "job_name": str(summary.get("suite_run_id") or suite_dir.name),
        "source_kind": "suite",
        "source": did,
        "dataset_id": did,
        "dataset_version": ver,
        "dataset_ref": ref,
        "agent_label": agent_label,
        "model_label": model_label,
        "reasoning_effort": _reasoning_effort_from_summary(summary),
        "overlays": overlay_paths_from_job_overlay(overlay),
        "provider_label": str(summary.get("provider_label") or ""),
        "environment": _environment_from_overlay(overlay),
        "result": metrics.get("mean_score"),
        "pass_rate": metrics.get("pass_rate"),
        "mean_score": metrics.get("mean_score"),
        "metrics": metrics,
        "task_refs": _chart_task_refs(refs),
        "started": summary.get("created_at"),
        "duration": summary.get("duration"),
        "n_attempts": summary.get("n_attempts"),
        "trials_done": trials_done,
        "trials_total": n_tasks or len(refs),
        "exit_code": summary.get("exit_code"),
        "task_count": n_tasks or len(refs),
        "summary_path": str(suite_dir / "summary.json"),
        "note": summary.get("note") or "per-task evaluator verdicts only; no suite-level PASS",
    }
    _merge_live_progress(row, summary, suite_dir=suite_dir)
    return row


def _merge_live_progress(row: dict[str, Any], summary: dict[str, Any], *, suite_dir: Path) -> None:
    """Merge progress.json into a row backed by an in-progress summary snapshot.

    A live snapshot lists settled work only; ``progress.json`` still owns the
    planned unit count. Final summaries are untouched.
    """
    status = str(summary.get("status") or "").strip().lower() or None
    row["status"] = status
    if status not in {"running", "cancelling"}:
        return
    progress = _load_progress(suite_dir)
    if progress is None:
        return
    raw_metrics = row.get("metrics")
    metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
    row["progress"] = progress
    planned = int(progress.get("total") or 0)
    if planned:
        row["trials_total"] = planned
        row["task_count"] = planned
    row["trials_done"] = (
        int(metrics.get("n_pass") or 0)
        + int(metrics.get("n_fail") or 0)
        + int(metrics.get("n_error") or 0)
    )


def _load_progress(suite_dir: Path) -> dict[str, Any] | None:
    path = suite_dir / "progress.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _suite_run_ids(items: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for row in items:
        jid = str(row.get("job_id") or "")
        if jid:
            ids.add(jid)
    return ids


def _run_ids_from_summary(summary: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for ref in _ensure_task_refs(summary):
        rid = str(ref.get("run_id") or "").strip()
        if rid:
            ids.add(rid)
        extra = ref.get("attempt_run_ids")
        if isinstance(extra, list):
            for item in extra:
                text = str(item or "").strip()
                if text:
                    ids.add(text)
    for task in _task_dicts(summary):
        rid = str(task.get("run_id") or "").strip()
        if rid:
            ids.add(rid)
    for attempt in _attempt_dicts(summary):
        rid = str(attempt.get("run_id") or "").strip()
        if rid:
            ids.add(rid)
    return ids


def _referenced_run_ids(dataset_root: Path, suite_items: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    root = dataset_root.expanduser().resolve(strict=False)
    for row in suite_items:
        job_id = str(row.get("job_id") or "")
        if not job_id:
            continue
        try:
            summary = _load_summary(_suite_root(root) / job_id / "summary.json")
        except ConfigError:
            continue
        ids.update(_run_ids_from_summary(summary))
    return ids


def _iter_attempt_dirs(dataset_root: Path, *, manifest: Any = None) -> list[tuple[str, Path]]:
    root = dataset_root.expanduser().resolve(strict=False)
    found: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def _add(run_id: str, path: Path) -> None:
        if run_id in seen:
            return
        try:
            safe_id_segment(run_id, field="run_id")
        except ConfigError:
            return
        found.append((run_id, path))
        seen.add(run_id)

    db_runs = default_runs_root(root)
    if db_runs.is_dir():
        for child in db_runs.iterdir():
            if child.is_dir():
                _add(child.name, child)

    tasks_root_name = "tasks"
    man = manifest
    if man is None:
        with contextlib.suppress(ConfigError):
            man = load_dataset_manifest(root)
    if man is not None:
        tasks_root_name = man.tasks_root or "tasks"
    tasks_dir = root / tasks_root_name
    if tasks_dir.is_dir():
        for task_dir in tasks_dir.iterdir():
            if not task_dir.is_dir():
                continue
            local = default_runs_root(task_dir)
            if not local.is_dir():
                continue
            for child in local.iterdir():
                if child.is_dir():
                    _add(child.name, child)
    return found


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _environment_kind(lock: dict[str, Any], result: dict[str, Any]) -> str | None:
    """Box kind as written today: lock.environment, else result.kind."""
    for raw in (lock.get("environment"), result.get("kind")):
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    overlay = lock.get("job_overlay") if isinstance(lock.get("job_overlay"), dict) else None
    return _environment_from_overlay(overlay)


def _environment_from_overlay(overlay: dict[str, Any] | None) -> str | None:
    if not isinstance(overlay, dict):
        return None
    raw = overlay.get("environment")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _first_run_id(summary: dict[str, Any]) -> str | None:
    for ref in _ensure_task_refs(summary):
        rid = ref.get("run_id")
        if isinstance(rid, str) and rid.strip():
            return rid.strip()
        ids = ref.get("attempt_run_ids")
        if isinstance(ids, list):
            for item in ids:
                if isinstance(item, str) and item.strip():
                    return item.strip()
    attempts = summary.get("attempts")
    if isinstance(attempts, list):
        for row in attempts:
            if not isinstance(row, dict):
                continue
            rid = row.get("run_id")
            if isinstance(rid, str) and rid.strip():
                return rid.strip()
    return None


def _overlay_from_job_summary(
    summary: dict[str, Any], *, dataset_root: Path
) -> dict[str, Any] | None:
    """Suite overlay, else the Attempt lock written from profiles.yaml."""
    overlay = summary.get("job_overlay") if isinstance(summary.get("job_overlay"), dict) else None
    if _environment_from_overlay(overlay):
        return overlay
    profiles = overlay.get("agent_profiles") if isinstance(overlay, dict) else None
    if isinstance(profiles, dict) and profiles:
        return overlay
    from ageval.application.suite.suite_config_fingerprint import load_run_lock_doc

    lock = load_run_lock_doc(dataset_root, _first_run_id(summary))
    if not isinstance(lock, dict):
        return overlay
    lock_overlay = lock.get("job_overlay") if isinstance(lock.get("job_overlay"), dict) else None
    env = _environment_from_overlay(lock_overlay) or (
        str(lock["environment"]).strip()
        if isinstance(lock.get("environment"), str) and str(lock.get("environment")).strip()
        else None
    )
    if lock_overlay is not None:
        if env and not _environment_from_overlay(lock_overlay):
            return {**lock_overlay, "environment": env}
        return lock_overlay
    if env:
        return {"environment": env}
    return overlay


def _phase_timing(src: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(src, dict):
        return None
    timing = src.get("phase_timing")
    return timing if isinstance(timing, dict) else None


def _started_at(phase_timing: dict[str, Any] | None) -> str | None:
    if not isinstance(phase_timing, dict):
        return None
    raw = phase_timing.get("started_at")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _duration_label(phase_timing: dict[str, Any] | None) -> str | None:
    if not isinstance(phase_timing, dict):
        return None
    total_ms = phase_timing.get("total_ms")
    if isinstance(total_ms, int | float) and not isinstance(total_ms, bool):
        return format_duration_ms(float(total_ms))
    return None


class AttemptClock(TypedDict):
    """One Attempt's phase clock. Stamps are present only when the seal wrote them."""

    duration_ms: float
    started_at: NotRequired[str]
    finished_at: NotRequired[str]


class TaskTiming(TypedDict):
    """Mean duration for a suite task row, plus the finish stamp the pace board orders on."""

    duration: str | None
    duration_ms: float | None
    finished_at: str | None


def _attempt_clock(root: Path, run_id: str) -> AttemptClock | None:
    """One Attempt's phase clock: ``duration_ms``, and stamps when sealed."""
    text = str(run_id or "").strip()
    if not text:
        return None
    try:
        run_dir = resolve_attempt_run_dir(root, text)
    except ConfigError:
        return None
    for name in ("summary.json", "result.json"):
        raw = _read_json_object(run_dir / name)
        if raw is None:
            continue
        timing = raw.get("phase_timing")
        if not isinstance(timing, dict):
            result = raw.get("result")
            timing = result.get("phase_timing") if isinstance(result, dict) else None
        if not isinstance(timing, dict):
            continue
        total_ms = timing.get("total_ms")
        if not isinstance(total_ms, int | float) or isinstance(total_ms, bool):
            continue
        clock: AttemptClock = {"duration_ms": float(total_ms)}
        started = timing.get("started_at")
        if isinstance(started, str) and started.strip():
            clock["started_at"] = started.strip()
        finished = timing.get("finished_at")
        if isinstance(finished, str) and finished.strip():
            clock["finished_at"] = finished.strip()
        return clock
    return None


def _latest_stamp(values: list[str]) -> str | None:
    best_value: str | None = None
    best_key: datetime | None = None
    for value in values:
        try:
            key = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if best_key is None or key > best_key:
            best_key = key
            best_value = value
    return best_value


def _task_timing(root: Path, run_ids: list[str], fallback: object) -> TaskTiming:
    """Mean Attempt duration, plus the finish stamp the pace board orders on."""
    clocks = [clock for rid in run_ids if (clock := _attempt_clock(root, rid)) is not None]
    if clocks:
        duration_ms = sum(float(clock["duration_ms"]) for clock in clocks) / len(clocks)
        finished = [stamp for clock in clocks if (stamp := clock.get("finished_at"))]
        return {
            "duration": format_duration_ms(duration_ms),
            "duration_ms": duration_ms,
            "finished_at": _latest_stamp(finished),
        }
    label = fallback.strip() if isinstance(fallback, str) and fallback.strip() else None
    return {"duration": label, "duration_ms": None, "finished_at": None}


def _reasoning_effort_from_summary(summary: dict[str, Any]) -> str:
    from ageval.config.profiles import (
        join_display_names,
        reasoning_effort_from_overlay,
        reasoning_effort_from_profile,
    )

    overlay = summary.get("job_overlay")
    effort = reasoning_effort_from_overlay(overlay if isinstance(overlay, dict) else None)
    if effort:
        return effort
    actors = summary.get("actors_summary")
    if not isinstance(actors, list):
        return ""
    found: list[str] = []
    for raw in actors:
        if not isinstance(raw, dict):
            continue
        item = reasoning_effort_from_profile(raw)
        if item:
            found.append(item)
    return join_display_names(found)


def _labels_from_lock(lock: dict[str, Any], result: dict[str, Any]) -> tuple[str, str]:
    """Prefer sealed result labels; else Core display_labels_from_overlay."""
    from ageval.config.profiles import display_labels_from_overlay

    agent = result.get("agent_label") or lock.get("agent_label")
    model = result.get("model_label") or lock.get("model_label")
    a = agent.strip() if isinstance(agent, str) else ""
    m = model.strip() if isinstance(model, str) else ""
    if a and m:
        return a, m
    overlay = lock.get("job_overlay") if isinstance(lock.get("job_overlay"), dict) else None
    derived_a, derived_m = display_labels_from_overlay(overlay)
    return a or derived_a, m or derived_m


def _single_job_row(
    evidence: Path, *, run_id: str, dataset_root: Path, manifest: Any = None
) -> dict[str, Any]:
    from ageval.evidence.attempt_record import read_attempt_result

    result = read_attempt_result(evidence) or {}
    lock = _read_json_object(evidence / "lock.json") or {}
    summary = _read_json_object(evidence / "summary.json") or {}
    task_id = str(result.get("task_id") or lock.get("task_id") or "")
    status = str(result.get("status") or "")
    score = result.get("score")
    phase_timing = _phase_timing(summary)
    started = _started_at(phase_timing)
    agent_label, model_label = _labels_from_lock(lock, result)
    from ageval.config.overlay_files import overlay_paths_from_job_overlay
    from ageval.config.profiles import reasoning_effort_from_overlay

    overlay = lock.get("job_overlay") if isinstance(lock.get("job_overlay"), dict) else None
    del manifest
    did, ver = dataset_identity(lock, location=str(evidence / "lock.json"))
    ref = dataset_ref(did, ver)
    return {
        "job_id": run_id,
        "job_name": run_id,
        "source_kind": "single",
        "source": task_id or "single",
        "dataset_id": did,
        "dataset_version": ver,
        "dataset_ref": ref,
        "agent_label": agent_label,
        "model_label": model_label,
        "reasoning_effort": reasoning_effort_from_overlay(overlay),
        "overlays": overlay_paths_from_job_overlay(overlay) if overlay else [],
        "provider_label": str(lock.get("provider_label") or result.get("provider_label") or ""),
        "environment": _environment_kind(lock, result),
        "result": score,
        "pass_rate": 1.0 if status.upper() == "PASS" else 0.0,
        "mean_score": score,
        "metrics": {"n_tasks": 1, "n_pass": 1 if status.upper() == "PASS" else 0},
        "started": started,
        "duration": _duration_label(phase_timing),
        "n_attempts": 1,
        "trials_done": 1,
        "trials_total": 1,
        "exit_code": result.get("exit_code"),
        "task_count": 1,
        "summary_path": str(evidence / "result.json"),
        "task_id": task_id,
        "status": status.upper() if status else None,
        "score": score,
        "run_id": run_id,
        "error": result.get("error"),
        "limit": result.get("limit"),
        "note": "single-task attempt; per-task evaluator verdicts only",
    }


def list_jobs(dataset_root: Path | str) -> dict[str, Any]:
    root = Path(dataset_root).expanduser().resolve(strict=False)
    suite_root = _suite_root(root)
    man = None
    with contextlib.suppress(ConfigError):
        man = load_dataset_manifest(root)
    items: list[dict[str, Any]] = []
    claimed: set[str] = set()
    if suite_root.is_dir():
        for child in sorted(suite_root.iterdir(), key=lambda p: p.name, reverse=True):
            if not child.is_dir():
                continue
            summary_path = child / "summary.json"
            if summary_path.is_file():
                try:
                    summary = _load_summary(summary_path)
                except ConfigError:
                    continue
                row = _job_row(summary, suite_dir=child, dataset_root=root, manifest=man)
                items.append(row)
                jid = str(row.get("job_id") or "")
                if jid:
                    claimed.add(jid)
                claimed.update(_run_ids_from_summary(summary))
                continue
            progress = _load_progress(child)
            if progress is not None:
                row = _in_progress_suite_row(
                    progress, suite_dir=child, dataset_root=root, manifest=man
                )
                items.append(row)
                jid = str(row.get("job_id") or "")
                if jid:
                    claimed.add(jid)

    claimed.update(_suite_run_ids(items))
    for run_id, evidence in _iter_attempt_dirs(root, manifest=man):
        if run_id in claimed:
            continue
        if not (evidence / "result.json").is_file():
            # Live/incomplete Attempt — not a finished Job; delete would
            # rmtree a suite that is still writing.
            continue
        items.append(_single_job_row(evidence, run_id=run_id, dataset_root=root, manifest=man))
    items.sort(key=lambda r: str(r.get("started") or r.get("job_id") or ""), reverse=True)

    dataset_id = man.dataset_id if man is not None else None
    version = man.version if man is not None else None
    if dataset_id is None:
        from ageval.config.harbor_layout import open_harbor_root

        with contextlib.suppress(ConfigError):
            opened = open_harbor_root(root)
            dataset_id = opened.manifest.dataset_id
            version = opened.manifest.version

    return {
        "ok": True,
        "dataset_id": dataset_id,
        "version": version,
        "root": str(root),
        "items": items,
        "count": len(items),
        "commands": commands_for(root),
    }


def job_overlay_mapping(dataset_root: Path | str, job_id: str) -> dict[str, Any] | None:
    """Secret-free job_overlay from a suite summary or single-attempt lock."""
    root = Path(dataset_root).expanduser().resolve(strict=False)
    job_id = safe_id_segment(job_id, field="job_id")
    suite_summary = _suite_root(root) / job_id / "summary.json"
    if suite_summary.is_file():
        summary = _load_summary(suite_summary)
        overlay = summary.get("job_overlay")
        return overlay if isinstance(overlay, dict) else None
    for rid, evidence in _iter_attempt_dirs(root):
        if rid != job_id:
            continue
        lock = _read_json_object(evidence / "lock.json") or {}
        overlay = lock.get("job_overlay")
        return overlay if isinstance(overlay, dict) else None
    return None


_TASK_SORT_KEYS = frozenset({"task_id", "agent_label", "model_label", "score", "status"})
_NATURAL_CHUNK = re.compile(r"(\d+)")
DEFAULT_TASK_PAGE_SIZE = 50
MAX_TASK_PAGE_SIZE = 200


def _reason_text(row: dict[str, Any]) -> str:
    """Same key the task-table reason filter uses in the Viewer."""
    status = str(row.get("status") or "").upper()
    error = row.get("error")
    if status == "ERROR" or _error_present(error):
        fields = _error_fields(error)
        if fields is not None:
            title, message = fields
            if title:
                return title
            if message:
                return message
        return _plain_error(error)
    limit = row.get("limit")
    if isinstance(limit, str) and limit.strip():
        return limit.strip()
    return ""


def _error_present(error: object) -> bool:
    if error is None or error == "":
        return False
    return isinstance(error, (str, dict))


def _error_fields(error: object) -> tuple[str, str] | None:
    if not isinstance(error, dict):
        return None
    title = error.get("title")
    message = error.get("message")
    title_s = title.strip() if isinstance(title, str) else ""
    message_s = message.strip() if isinstance(message, str) else ""
    if not title_s and not message_s:
        return None
    if message_s == title_s:
        message_s = ""
    return title_s, message_s


def _plain_error(error: object) -> str:
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        return json.dumps(error, ensure_ascii=False, separators=(",", ":"))
    if error is None or error == "":
        return ""
    return str(error)


def _distinct_reasons(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        value = _reason_text(row)
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _natural_cmp(left: str, right: str) -> int:
    left_parts = _NATURAL_CHUNK.split(left.casefold())
    right_parts = _NATURAL_CHUNK.split(right.casefold())
    for lpart, rpart in zip(left_parts, right_parts, strict=False):
        if lpart == rpart:
            continue
        if lpart.isdigit() and rpart.isdigit():
            diff = int(lpart) - int(rpart)
            return -1 if diff < 0 else 1 if diff > 0 else 0
        if lpart < rpart:
            return -1
        return 1
    return (len(left_parts) > len(right_parts)) - (len(left_parts) < len(right_parts))


def _cmp_task_values(left: object, right: object, direction: str) -> int:
    """Nulls stay last. Numbers compare as numbers. Text is numeric-aware."""
    if left is None and right is None:
        return 0
    if left is None:
        return 1
    if right is None:
        return -1
    mul = 1 if direction == "asc" else -1
    if (
        isinstance(left, (int, float))
        and isinstance(right, (int, float))
        and not isinstance(left, bool)
        and not isinstance(right, bool)
    ):
        diff = float(left) - float(right)
        if diff < 0:
            return -mul
        if diff > 0:
            return mul
        return 0
    return mul * _natural_cmp(str(left), str(right))


def _pace_row(row: dict[str, Any]) -> dict[str, Any]:
    run_ids = row.get("attempt_run_ids")
    return {
        "task_id": row.get("task_id"),
        "status": row.get("status"),
        "score": row.get("score"),
        "duration_ms": row.get("duration_ms"),
        "finished_at": row.get("finished_at"),
        "run_id": row.get("run_id"),
        "attempt_run_ids": list(run_ids) if isinstance(run_ids, list) else [],
    }


def paginate_job_tasks(
    payload: dict[str, Any],
    *,
    page: int,
    page_size: int,
    reason: str,
    sort: str | None,
    direction: str | None,
) -> dict[str, Any]:
    """One page of task rows, plus a slim pace row for every task.

    The duration plot reads ``pace`` (the whole suite). The table reads
    ``tasks`` (this page only). Omitting ``page`` keeps the unpaged payload.
    """
    tasks = [row for row in (payload.get("tasks") or []) if isinstance(row, dict)]
    pace = [_pace_row(row) for row in tasks]
    reasons = _distinct_reasons(tasks)
    filtered = tasks
    reason_key = reason.strip()
    if reason_key and reason_key != "all":
        filtered = [row for row in tasks if _reason_text(row) == reason_key]
    ordered = list(filtered)
    sort_key = sort if sort in _TASK_SORT_KEYS else None
    sort_dir = direction if direction in {"asc", "desc"} else None
    if sort_key and sort_dir:
        ordered.sort(
            key=cmp_to_key(
                lambda left, right: _cmp_task_values(
                    left.get(sort_key), right.get(sort_key), sort_dir
                )
            )
        )
    size = page_size if isinstance(page_size, int) else DEFAULT_TASK_PAGE_SIZE
    size = min(MAX_TASK_PAGE_SIZE, max(1, size))
    pages = max(1, (len(ordered) + size - 1) // size) if ordered else 1
    current = min(max(int(page), 1), pages)
    start = (current - 1) * size
    out = dict(payload)
    out["tasks"] = ordered[start : start + size]
    out["task_count"] = len(tasks)
    out["total"] = len(ordered)
    out["page"] = current
    out["page_size"] = size
    out["pace"] = pace
    out["reasons"] = reasons
    return out


def get_job(
    dataset_root: Path | str,
    job_id: str,
    *,
    page: int | None = None,
    page_size: int = DEFAULT_TASK_PAGE_SIZE,
    reason: str = "",
    sort: str | None = None,
    direction: str | None = None,
) -> dict[str, Any]:
    def finish(payload: dict[str, Any]) -> dict[str, Any]:
        if page is None:
            return payload
        return paginate_job_tasks(
            payload,
            page=page,
            page_size=page_size,
            reason=reason,
            sort=sort,
            direction=direction,
        )

    root = Path(dataset_root).expanduser().resolve(strict=False)
    job_id = safe_id_segment(job_id, field="job_id")
    suite_dir = _suite_root(root) / job_id
    # Confine suite dir under dataset root
    suite_resolved = suite_dir.resolve(strict=False)
    try:
        suite_resolved.relative_to(root)
    except ValueError as exc:
        raise ConfigError(
            "invalid_package",
            "job path escapes dataset sandbox",
            location=job_id,
        ) from exc
    summary_path = suite_dir / "summary.json"
    if not summary_path.is_file():
        progress = _load_progress(suite_dir)
        if progress is not None:
            return finish(_get_in_progress_suite_job(root, suite_dir=suite_dir, progress=progress))
        return finish(_get_single_job(root, job_id))
    summary = _load_summary(summary_path)
    job = _job_row(summary, suite_dir=suite_dir, dataset_root=root)
    progress = _load_progress(suite_dir)
    if progress is not None:
        job["progress"] = progress
    refs = _ensure_task_refs(summary)
    # Prefer full task rows when present (score/status/error)
    by_id: dict[str, dict[str, Any]] = {}
    for t in _task_dicts(summary):
        if t.get("task_id"):
            by_id[str(t["task_id"])] = t

    task_rows: list[dict[str, Any]] = []
    for ref in refs:
        tid = str(ref.get("task_id") or "")
        full = by_id.get(tid, {})
        status = str(full.get("status") or ref.get("status") or "")
        score = full.get("score") if full.get("score") is not None else ref.get("score")
        error = full.get("error") if full else ref.get("error")
        limit = full.get("limit") if full else ref.get("limit")
        attempt_rows = _attempts_for_task(summary, tid)
        if not attempt_rows:
            rid = full.get("run_id") or ref.get("run_id")
            if rid:
                attempt_rows = [
                    {
                        "task_id": tid,
                        "run_id": rid,
                        "status": status,
                        "score": score,
                        "error": error,
                        "limit": limit,
                        "exit_code": full.get("exit_code"),
                        "duration": full.get("duration"),
                    }
                ]
        attempt_run_ids = [
            str(a.get("run_id")).strip()
            for a in attempt_rows
            if a.get("run_id") and str(a.get("run_id")).strip()
        ]
        n_val = full.get("n") if full.get("n") is not None else ref.get("n")
        if n_val is None:
            n_val = len(attempt_run_ids) or None
        # Paged responses only render this page. Skip the per-attempt stamp
        # lookup for rows the table will not return; the pace plot does not
        # read previous[].
        previous = _previous_entries(
            ref,
            attempt_rows,
            dataset_root=None if page is not None else root,
        )
        timing = _task_timing(root, attempt_run_ids, full.get("duration"))
        task_rows.append(
            {
                "task_id": tid,
                "status": status.upper() if status else None,
                "score": score,
                "run_id": attempt_run_ids[0]
                if attempt_run_ids
                else full.get("run_id") or ref.get("run_id"),
                "attempt_run_ids": attempt_run_ids,
                "previous": previous,
                "attempts": attempt_rows,
                "error": error,
                "limit": limit,
                "exit_code": full.get("exit_code"),
                "agent_label": job.get("agent_label") or "",
                "model_label": job.get("model_label") or "",
                "reasoning_effort": job.get("reasoning_effort") or "",
                "provider_label": job.get("provider_label") or "",
                "dataset": job.get("dataset_ref") or job.get("dataset_id"),
                "duration": timing["duration"],
                "duration_ms": timing["duration_ms"],
                "finished_at": timing["finished_at"],
                "phase_timing": full.get("phase_timing"),
                "n": n_val,
                "c": full.get("c") if full.get("c") is not None else ref.get("c"),
            }
        )

    settled_ids = {str(row.get("task_id") or "") for row in task_rows}
    task_rows.extend(_planned_pending_rows(progress, settled_ids))

    return finish(
        {
            "ok": True,
            "job": job,
            "tasks": task_rows,
            "task_count": len(task_rows),
            "progress": progress,
            "commands": commands_for(root),
            "note": job.get("note"),
        }
    )


def _get_in_progress_suite_job(
    root: Path, *, suite_dir: Path, progress: dict[str, Any]
) -> dict[str, Any]:
    job = _in_progress_suite_row(progress, suite_dir=suite_dir, dataset_root=root)
    raw_running = progress.get("running")
    running: list[Any] = raw_running if isinstance(raw_running, list) else []
    task_rows: list[dict[str, Any]] = []
    for item in running:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("task_id") or "")
        if not tid:
            continue
        task_rows.append(
            {
                "task_id": tid,
                "status": str(item.get("phase") or "running").upper(),
                "score": None,
                "run_id": None,
                "attempt_run_ids": [],
                "attempts": [],
                "error": None,
                "limit": None,
                "n": 1,
            }
        )
    present_ids = {str(row.get("task_id") or "") for row in task_rows}
    task_rows.extend(_planned_pending_rows(progress, present_ids))
    return {
        "ok": True,
        "job": job,
        "tasks": task_rows,
        "task_count": int(progress.get("total") or len(task_rows) or 0),
        "progress": progress,
        "commands": commands_for(root),
        "note": job.get("note"),
    }


def _get_single_job(root: Path, job_id: str) -> dict[str, Any]:
    evidence = None
    for rid, path in _iter_attempt_dirs(root):
        if rid == job_id:
            evidence = path
            break
    if evidence is None:
        raise ConfigError(
            "unknown_task",
            f"suite run not found: {job_id}",
            location=job_id,
        )
    job = _single_job_row(evidence, run_id=job_id, dataset_root=root)
    task_id = str(job.get("task_id") or "")
    task_rows = [
        {
            "task_id": task_id,
            "status": job.get("status"),
            "score": job.get("score"),
            "run_id": job_id,
            "attempt_run_ids": [job_id],
            "attempts": [
                {
                    "task_id": task_id,
                    "run_id": job_id,
                    "status": job.get("status"),
                    "score": job.get("score"),
                    "error": job.get("error"),
                    "limit": job.get("limit"),
                    "exit_code": job.get("exit_code"),
                    "duration": job.get("duration"),
                    "started": job.get("started"),
                }
            ],
            "error": job.get("error"),
            "limit": job.get("limit"),
            "exit_code": job.get("exit_code"),
            "agent_label": job.get("agent_label") or "",
            "model_label": job.get("model_label") or "",
            "reasoning_effort": job.get("reasoning_effort") or "",
            "provider_label": job.get("provider_label") or "",
            "dataset": job.get("dataset_ref") or job.get("dataset_id"),
            "duration": job.get("duration"),
            "n": 1,
        }
    ]
    return {
        "ok": True,
        "job": job,
        "tasks": task_rows,
        "task_count": 1,
        "progress": None,
        "commands": commands_for(root, task_id=task_id or None),
        "note": job.get("note"),
    }


def get_job_task(dataset_root: Path | str, job_id: str, task_id: str) -> dict[str, Any]:
    task_id = safe_id_segment(task_id, field="task_id")
    job_payload = get_job(dataset_root, job_id)
    match = None
    for row in job_payload["tasks"]:
        if row.get("task_id") == task_id:
            match = row
            break
    if match is None:
        raise ConfigError(
            "unknown_task",
            f"task {task_id!r} not in suite run {job_id!r}",
            location=task_id,
        )

    root = Path(dataset_root).expanduser().resolve(strict=False)
    cmds = commands_for(root, task_id=task_id)
    # One-liner re-run command for the task (or full suite)
    run_cmd = cmds.get("run_task") or cmds.get("run_suite")

    started = job_payload["job"].get("started")
    attempt_src = match.get("attempts")
    if not isinstance(attempt_src, list) or not attempt_src:
        rid = match.get("run_id")
        attempt_src = [
            {
                "run_id": rid,
                "status": match.get("status"),
                "score": match.get("score"),
                "error": match.get("error"),
                "limit": match.get("limit"),
                "exit_code": match.get("exit_code"),
                "duration": match.get("duration"),
            }
        ]
        if not rid:
            attempt_src = []
    trials_out: list[dict[str, Any]] = []
    for row in attempt_src:
        if not isinstance(row, dict):
            continue
        rid = row.get("run_id") or match.get("run_id")
        if not rid:
            continue
        score = row.get("score") if row.get("score") is not None else match.get("score")
        trials_out.append(
            {
                "trial_id": rid,
                "task_id": task_id,
                "status": row.get("status") or match.get("status"),
                "reward": score,
                "score": score,
                "duration": row.get("duration") or match.get("duration"),
                "started": row.get("started") or started,
                "error": row["error"] if "error" in row else match.get("error"),
                "limit": row["limit"] if "limit" in row else match.get("limit"),
                "run_id": rid,
                "exit_code": row.get("exit_code")
                if row.get("exit_code") is not None
                else match.get("exit_code"),
                "attempt_index": row.get("attempt_index"),
            }
        )

    return {
        "ok": True,
        "job": job_payload["job"],
        "task": match,
        "trials": trials_out,
        "agent_label": match.get("agent_label") or job_payload["job"].get("agent_label"),
        "model_label": match.get("model_label") or job_payload["job"].get("model_label"),
        "reasoning_effort": match.get("reasoning_effort")
        or job_payload["job"].get("reasoning_effort"),
        "provider_label": match.get("provider_label") or job_payload["job"].get("provider_label"),
        "dataset": match.get("dataset") or job_payload["job"].get("source"),
        "commands": cmds,
        "run_command": run_cmd,
        "breadcrumb": [
            {"label": "Jobs", "href": "/"},
            {"label": job_id, "href": f"/jobs/{job_id}"},
            {"label": task_id, "href": None},
        ],
        "note": "per-task evaluator verdicts only; no suite-level PASS",
    }
