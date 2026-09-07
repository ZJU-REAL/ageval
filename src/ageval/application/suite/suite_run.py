"""Dataset suite run: task_id-axis scheduling (+ multi-attempt Always-k, #47).

Orthogonal to Campaign (parameter matrix on one task). Application-layer only;
does not invent suite-level PASS.

``n_attempts`` / k-attempt and resume are **CLI / job** parameters only — never
package identity or ``config_fingerprint`` inputs.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ageval.application.composition import build_run_attempt
from ageval.application.suite import document
from ageval.application.suite.suite_config_fingerprint import collect_suite_config
from ageval.application.suite.suite_metrics import (
    aggregate_k_metrics,
    extend_slot_previous,
    flatten_legacy_tasks_as_attempts,
    metrics_payload_from_k_agg,
    slot_key,
    task_refs_for_summary,
)
from ageval.application.suite.suite_usage import collect_suite_usage
from ageval.attempt.ctx import PhaseObserver
from ageval.config.dataset import list_tasks, load_dataset_manifest
from ageval.config.errors import ConfigError
from ageval.registry.resolve import resolve_dataset_root

# Instrumentation for tests: peaks concurrent in-flight workers.
_inflight_lock = asyncio.Lock()
_inflight_current = 0
_inflight_peak = 0


def reset_inflight_metrics() -> None:
    global _inflight_current, _inflight_peak
    _inflight_current = 0
    _inflight_peak = 0


def get_inflight_peak() -> int:
    return _inflight_peak


@dataclass
class SuitePlan:
    dataset_id: str
    dataset_version: str
    dataset_root: Path
    task_ids: list[str]
    max_concurrent_tasks: int
    n_attempts: int = 1
    # System id: 8 hex (local job locator only; not package identity). No suite_ prefix.
    suite_run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


def plan_suite_run(
    dataset_ref: str | Path,
    *,
    task_id: str | None = None,
    max_concurrent_tasks: int | None = None,
    n_attempts: int | None = None,
    suite_run_id: str | None = None,
) -> SuitePlan:
    """Build a suite plan from Dataset root/ref and optional single-task filter.

    Parameters
    ----------
    n_attempts:
        Always-k sample budget per task (CLI / job only). Default 1.
        Does **not** change package identity or fingerprint.
    suite_run_id:
        When resuming, reuse an existing suite run id.
    """
    root = resolve_dataset_root(dataset_ref)
    man = load_dataset_manifest(root)
    if task_id:
        # Validate membership via resolve path
        from ageval.config.dataset import resolve_task

        resolve_task(root, task_id, manifest=man)
        ids = [task_id]
    else:
        ids = list_tasks(root, manifest=man)

    k = 1 if n_attempts is None else n_attempts
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ConfigError(
            "invalid_override",
            "n_attempts must be an integer ≥ 1",
            location="--n-attempts",
        )

    n = max_concurrent_tasks
    if n is None:
        if man.defaults and man.defaults.max_concurrent_tasks is not None:
            n = man.defaults.max_concurrent_tasks
        else:
            n = 1
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ConfigError(
            "invalid_override",
            "max_concurrent_tasks must be an integer ≥ 1",
            location="--max-concurrent-tasks",
        )
    # Single unit (one task × one attempt): concurrency is irrelevant → force 1.
    # Multi-attempt or multi-task: keep pool size so parallel only speeds wall time.
    if len(ids) == 1 and k == 1:
        n = 1

    plan = SuitePlan(
        dataset_id=man.dataset_id,
        dataset_version=man.version,
        dataset_root=root,
        task_ids=ids,
        max_concurrent_tasks=n,
        n_attempts=k,
    )
    if suite_run_id is not None and str(suite_run_id).strip():
        plan.suite_run_id = str(suite_run_id).strip()
    return plan


def suite_summary_path(dataset_root: Path, suite_run_id: str) -> Path:
    return document.summary_path(dataset_root.expanduser().resolve(strict=False), suite_run_id)


def is_suite_run_locator(
    run_id: str,
    *,
    dataset_root: Path | str | None = None,
    control_kind: str | None = None,
) -> bool:
    """True if *run_id* names a suite job.

    Detection (any):
    - ControlStore payload ``kind == suite``
    - Directory ``.ageval/suite-runs/<run_id>`` under *dataset_root*
    """
    rid = str(run_id or "").strip()
    if not rid:
        return False
    if str(control_kind or "").strip() == "suite":
        return True
    if dataset_root is None:
        return False
    root = Path(dataset_root).expanduser().resolve(strict=False)
    return document.suite_dir(root, rid).is_dir()


def load_suite_summary(dataset_root: Path, suite_run_id: str) -> dict[str, Any]:
    """Load an existing suite ``summary.json`` or raise ConfigError."""
    return document.load_suite_summary(dataset_root, suite_run_id)


def extract_run_id(dataset_root: Path, *candidates: object) -> str | None:
    """Extract Attempt ``run_id`` (directory name under ``.ageval/runs/``).

    Suite summary only stores ``run_id``; local path is always
    ``{dataset_root}/.ageval/runs/{run_id}/``. Host absolute paths must not appear.
    """
    root = dataset_root.expanduser().resolve(strict=False)
    for raw in candidates:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        path = Path(text)
        name = path.name
        # Bare id, ``.ageval/runs/<id>``, or ``.../runs/<id>``
        if (
            name.startswith("sha256_")
            and "_run_" in name
            and ("/" not in text.rstrip("/") or "runs" in path.parts or text.startswith(".ageval/"))
        ):
            return name
        try:
            abs_path = path if path.is_absolute() else (root / path)
            abs_path = abs_path.resolve(strict=False)
            rel = abs_path.relative_to(root)
            parts = rel.parts
            if len(parts) >= 3 and parts[0] == ".ageval" and parts[1] == "runs":
                return parts[2]
        except (ValueError, OSError):
            parts = path.parts
            if "runs" in parts:
                idx = parts.index("runs")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
            if name.startswith("sha256_") and "_run_" in name:
                return name
    return None


def planned_units(plan: SuitePlan) -> list[tuple[str, int]]:
    """Expand Always-k units: ``(task_id, attempt_index)`` for index in ``0..k-1``."""
    return [(tid, i) for tid in plan.task_ids for i in range(plan.n_attempts)]


def _is_cancelled_placeholder(row: Mapping[str, Any]) -> bool:
    """Synthetic suite-cancel rows (never ran) — retriable on resume."""
    if str(row.get("phase") or "") == "cancelled":
        return True
    return str(row.get("error") or "") == "suite_cancelled"


_FINISHED_PROGRESS = frozenset(
    {"complete", "completed", "finished", "done", "cancelled", "canceled"}
)


def _existing_attempt_keys(attempts: list[dict[str, Any]]) -> set[tuple[str, int]]:
    """Keys of finished attempts that resume must **not** re-run.

    Suite-cancel placeholders (``phase: cancelled`` / ``error: suite_cancelled``)
    are **excluded** so ``--resume-suite`` can top up Always-k samples; otherwise
    pass@k / pass^k stay permanently deflated.
    """
    keys: set[tuple[str, int]] = set()
    for row in attempts:
        if _is_cancelled_placeholder(row):
            continue
        tid, idx = slot_key(row)
        if not tid:
            continue
        keys.add((tid, idx))
    return keys


def suite_is_settled(dataset_root: Path, suite_run_id: str) -> bool:
    """True when the suite is not in-flight and has no pending cancel request."""
    if is_suite_cancel_requested(dataset_root, suite_run_id):
        return False
    progress_path = (
        document.suite_dir(dataset_root.expanduser().resolve(strict=False), suite_run_id)
        / "progress.json"
    )
    if not progress_path.is_file():
        return True
    try:
        data = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    status = str(data.get("status") or "").strip().lower()
    return status in _FINISHED_PROGRESS


async def _run_one(
    plan: SuitePlan,
    task_id: str,
    attempt_index: int,
    *,
    overrides: dict[str, Any] | None,
    run_fn: Callable[..., Awaitable[Any]],
    profiles_path: Path | str | None = None,
    keep_workspace: bool = False,
    keep_vendor_raw: bool = False,
    on_phase: PhaseObserver | None = None,
) -> dict[str, Any]:
    """Run one (task_id, attempt_index) unit. Concurrency is owned by the claim pool."""
    global _inflight_current, _inflight_peak
    async with _inflight_lock:
        _inflight_current += 1
        _inflight_peak = max(_inflight_peak, _inflight_current)
    try:
        code, result = await run_fn(
            plan.dataset_root,
            task_id,
            overrides=overrides,
            profiles_path=profiles_path,
            keep_workspace=keep_workspace,
            keep_vendor_raw=keep_vendor_raw,
            on_phase=on_phase,
        )
        status = getattr(result, "status", None) or "ERROR"
        run_id = extract_run_id(
            plan.dataset_root,
            getattr(result, "evidence_path", None),
            getattr(result, "logs", None),
        )
        raw_metrics = getattr(result, "metrics", None)
        return {
            "task_id": task_id,
            "attempt_index": attempt_index,
            "exit_code": code,
            "status": status,
            "score": getattr(result, "score", None),
            "metrics": dict(raw_metrics) if isinstance(raw_metrics, dict) else {},
            "run_id": run_id,
            "error": None if code != 2 else str(getattr(result, "error_phase", None) or status),
            "phase": "terminal",
        }
    except ConfigError as exc:
        return {
            "task_id": task_id,
            "attempt_index": attempt_index,
            "exit_code": 2,
            "status": "ERROR",
            "score": None,
            "metrics": {},
            "run_id": None,
            "digest": None,
            "error": str(exc),
            "phase_timing": None,
            "duration": None,
            "phase": "error",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "task_id": task_id,
            "attempt_index": attempt_index,
            "exit_code": 2,
            "status": "ERROR",
            "score": None,
            "metrics": {},
            "run_id": None,
            "digest": None,
            "error": f"{type(exc).__name__}: {exc}",
            "phase_timing": None,
            "duration": None,
            "phase": "error",
        }
    finally:
        async with _inflight_lock:
            _inflight_current -= 1


def suite_dir_for(plan: SuitePlan) -> Path:
    return document.suite_dir(plan.dataset_root, plan.suite_run_id)


def cancel_request_path(dataset_root: Path, suite_run_id: str) -> Path:
    return (
        document.suite_dir(dataset_root.expanduser().resolve(strict=False), suite_run_id)
        / "cancel.requested"
    )


def is_suite_cancel_requested(dataset_root: Path, suite_run_id: str) -> bool:
    return cancel_request_path(dataset_root, suite_run_id).is_file()


def request_suite_cancel(dataset_root: Path, suite_run_id: str) -> Path:
    """Create cancel.requested so the suite loop stops starting new units."""
    path = cancel_request_path(dataset_root, suite_run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "ageval.suite.cancel/1",
                "suite_run_id": suite_run_id,
                "requested_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def clear_suite_cancel(dataset_root: Path, suite_run_id: str) -> bool:
    """Remove cancel.requested (e.g. before resume so the job can schedule again)."""
    path = cancel_request_path(dataset_root, suite_run_id)
    if not path.is_file():
        return False
    path.unlink(missing_ok=True)
    return True


def _write_suite_progress(
    plan: SuitePlan,
    *,
    done: int,
    total: int,
    running: list[dict[str, Any]],
    status: str = "running",
) -> None:
    """Job progress snapshot for viewer / status (D2)."""
    suite_dir = suite_dir_for(plan)
    suite_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "ageval.suite.progress/1",
        "suite_run_id": plan.suite_run_id,
        "dataset_id": plan.dataset_id,
        "dataset_version": plan.dataset_version,
        "status": status,
        "done": done,
        "total": total,
        "n_attempts": plan.n_attempts,
        "max_concurrent_tasks": plan.max_concurrent_tasks,
        # The full planned axis so the viewer can mark unrun tasks as pending.
        "task_ids": list(plan.task_ids),
        "running": running,
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "cancel_requested": is_suite_cancel_requested(plan.dataset_root, plan.suite_run_id),
    }
    out = suite_dir / "progress.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(out)


ProgressCallback = Callable[[dict[str, Any]], None]


def _phase_forwarder(
    on_progress: ProgressCallback | None,
    task_id: str,
    attempt_index: int,
) -> PhaseObserver | None:
    """Wrap a unit's attempt observer into ``unit_phase`` progress events."""
    if on_progress is None:
        return None

    def observe(event: str, phase: str) -> None:
        if event != "started":
            return
        on_progress(
            {
                "type": "unit_phase",
                "task_id": task_id,
                "attempt_index": attempt_index,
                "phase": phase,
            }
        )

    return observe


def _task_row_from_rollup(t: Mapping[str, Any]) -> dict[str, Any]:
    """One stable ``tasks[]`` row for any k (roll-up + primary attempt surface)."""
    nested = t.get("attempts") or []
    first: Mapping[str, Any] = nested[0] if nested and isinstance(nested[0], Mapping) else {}
    first_metrics = first.get("metrics") if isinstance(first.get("metrics"), dict) else {}
    return {
        "task_id": t.get("task_id"),
        "status": t.get("status"),
        "score": t.get("score"),
        "n": t.get("n"),
        "c": t.get("c"),
        "run_id": t.get("run_id"),
        "pass_at_k": t.get("pass_at_k") or {},
        "pass_power_k": t.get("pass_power_k") or {},
        "attempt_indices": t.get("attempt_indices"),
        # Primary attempt surface (k==1 ≡ the only sample; k>1 = first by index).
        "exit_code": first.get("exit_code"),
        "metrics": dict(first_metrics) if first_metrics else {},
        "digest": first.get("digest"),
        "error": first.get("error"),
        "attempt_index": first.get("attempt_index", 0),
        "phase_timing": first.get("phase_timing"),
        "duration": first.get("duration"),
    }


def _counts_and_exit_code(tasks_out: list[dict[str, Any]]) -> tuple[dict[str, int], int]:
    counts = {"pass": 0, "fail": 0, "error": 0, "skipped": 0}
    for row in tasks_out:
        st = str(row.get("status") or "").upper()
        if st == "PASS":
            counts["pass"] += 1
        elif st == "FAIL":
            counts["fail"] += 1
        else:
            counts["error"] += 1

    if counts["error"] > 0:
        exit_code = 2
    elif counts["fail"] > 0:
        exit_code = 1
    else:
        exit_code = 0
    return counts, exit_code


def _metrics_from_k_agg(k_agg: Mapping[str, Any], *, n_attempts: int) -> dict[str, Any]:
    metrics = metrics_payload_from_k_agg(k_agg)
    metrics["n_attempts"] = n_attempts
    return metrics


def _build_summary(
    plan: SuitePlan,
    attempts: list[dict[str, Any]],
    *,
    overrides: dict[str, Any] | None,
    profiles_path: Path | str | None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Roll attempts → tasks + metrics; write identity fields (no k in fingerprint)."""
    k_agg = aggregate_k_metrics(
        attempts,
        task_ids=plan.task_ids,
        n_attempts=plan.n_attempts,
    )
    task_rows: list[dict[str, Any]] = list(k_agg.pop("task_rows"))
    # Single shape for k==1 and k>1. Full samples live under ``attempts[]``.
    tasks_out = [_task_row_from_rollup(t) for t in task_rows]
    metrics = _metrics_from_k_agg(k_agg, n_attempts=plan.n_attempts)
    counts, exit_code = _counts_and_exit_code(tasks_out)

    # Fingerprint from one row per task (prefer a PASS attempt's run_id).
    fp_rows: list[dict[str, Any]] = []
    by_task_attempt: dict[str, list[dict[str, Any]]] = {}
    for a in attempts:
        tid = str(a.get("task_id") or "")
        by_task_attempt.setdefault(tid, []).append(a)
    for tid in plan.task_ids:
        rows = by_task_attempt.get(tid, [])
        pick = None
        for r in rows:
            if str(r.get("status") or "").upper() == "PASS" and r.get("run_id"):
                pick = r
                break
        if pick is None and rows:
            pick = rows[0]
        if pick is not None:
            fp_rows.append({"task_id": tid, "run_id": pick.get("run_id")})
        else:
            fp_rows.append({"task_id": tid, "run_id": None})

    config_fields = collect_suite_config(
        plan.dataset_root,
        fp_rows,
        overrides=overrides,
        task_ids=plan.task_ids,
        profiles_path=profiles_path,
    )
    usage_probe = {
        "attempts": attempts,
        "task_refs": task_refs_for_summary(tasks_out, attempts=attempts),
        "job_overlay": config_fields.get("job_overlay"),
        "model_label": config_fields.get("model_label") or "",
    }
    usage = collect_suite_usage(plan.dataset_root, usage_probe)
    if usage:
        metrics["usage"] = usage

    summary: dict[str, Any] = {
        "schema": "ageval.suite.summary/1",
        "suite_run_id": plan.suite_run_id,
        "dataset_id": plan.dataset_id,
        "dataset_version": plan.dataset_version,
        "max_concurrent_tasks": plan.max_concurrent_tasks,
        "n_attempts": plan.n_attempts,
        "task_ids": list(plan.task_ids),
        "attempts": list(attempts),
        "tasks": tasks_out,
        "task_refs": task_refs_for_summary(tasks_out, attempts=attempts),
        "counts": counts,
        # Observational aggregates (leaderboard / job stats); never suite PASS.
        "metrics": metrics,
        "exit_code": exit_code,
        "created_at": created_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "inflight_peak": get_inflight_peak(),
        "config_fingerprint": config_fields["config_fingerprint"],
        "config_homogeneous": config_fields["config_homogeneous"],
        "actors_summary": config_fields["actors_summary"],
        "agent_label": config_fields.get("agent_label") or "",
        "model_label": config_fields.get("model_label") or "",
        "note": "per-task evaluator verdicts only; no suite-level PASS",
    }
    if config_fields.get("job_overlay") is not None:
        summary["job_overlay"] = config_fields["job_overlay"]
    plugins = config_fields.get("plugins")
    if isinstance(plugins, list) and plugins:
        summary["plugins"] = plugins
    if any(isinstance(a.get("previous"), list) and a["previous"] for a in attempts):
        summary["amended"] = True
    return summary


def _settled_task_ids(plan: SuitePlan, attempts: list[dict[str, Any]]) -> list[str]:
    """Ids with at least one settled attempt: plan order first, then discovered.

    Mirrors the final summary's task-id union: resume-filter siblings that
    already settled stay listed.
    """
    settled = {str(a.get("task_id") or "") for a in attempts}
    present: list[str] = []
    seen: set[str] = set()

    def _add(tid: str) -> None:
        if tid and tid not in seen:
            seen.add(tid)
            present.append(tid)

    for tid in plan.task_ids:
        _add(tid)
    for tid in settled:
        _add(tid)
    return [tid for tid in present if tid in settled]


def _live_summary(
    plan: SuitePlan,
    attempts: list[dict[str, Any]],
    *,
    created_at: str,
    status: str,
) -> dict[str, Any]:
    """In-progress observational snapshot over *settled* attempts only.

    ``metrics.pass_rate`` counts only settled tasks; unrun planned ids appear
    nowhere. No config fingerprint: the final document is the fingerprint
    authority. ``status`` is ``running`` / ``cancelling`` — never a verdict.
    """
    settled_ids = _settled_task_ids(plan, attempts)
    k_agg = aggregate_k_metrics(
        attempts,
        task_ids=settled_ids,
        n_attempts=plan.n_attempts,
    )
    task_rows: list[dict[str, Any]] = list(k_agg.pop("task_rows"))
    tasks_out = [_task_row_from_rollup(t) for t in task_rows]
    metrics = _metrics_from_k_agg(k_agg, n_attempts=plan.n_attempts)
    counts, exit_code = _counts_and_exit_code(tasks_out)
    return {
        "schema": "ageval.suite.summary/1",
        "suite_run_id": plan.suite_run_id,
        "dataset_id": plan.dataset_id,
        "dataset_version": plan.dataset_version,
        "max_concurrent_tasks": plan.max_concurrent_tasks,
        "n_attempts": plan.n_attempts,
        "task_ids": settled_ids,
        "attempts": list(attempts),
        "tasks": tasks_out,
        "task_refs": task_refs_for_summary(tasks_out, attempts=attempts),
        "counts": counts,
        # Observational aggregates; a running snapshot is not suite PASS.
        "metrics": metrics,
        "exit_code": exit_code,
        "status": status,
        "created_at": created_at,
        "inflight_peak": get_inflight_peak(),
        "note": "suite in progress; observational snapshot of settled tasks",
    }


def _write_summary(plan: SuitePlan, summary: dict[str, Any]) -> dict[str, Any]:
    suite_dir = document.suite_dir(plan.dataset_root, plan.suite_run_id)
    suite_dir.mkdir(parents=True, exist_ok=True)
    out = suite_dir / "summary.json"
    tmp = out.with_suffix(".tmp")
    # summary_path is host-local; keep off the durable document? Historical
    # code put it only on the returned dict, not always on disk — write clean.
    disk = {k: v for k, v in summary.items() if k != "summary_path"}
    tmp.write_text(json.dumps(disk, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(out)
    summary["summary_path"] = str(out)
    return summary


def _assert_replace_slots(
    plan: SuitePlan,
    existing: list[dict[str, Any]],
    old_summary: Mapping[str, Any],
    replace: set[tuple[str, int]],
    overrides: dict[str, Any] | None,
    profiles_path: Path | str | None,
) -> None:
    """Fail closed: named slot must exist; binding family must match the suite."""
    finished = _existing_attempt_keys(existing)
    planned = set(plan.task_ids)
    for tid, idx in sorted(replace):
        if tid not in planned:
            raise ConfigError(
                "suite_replace_slot_missing",
                f"replace-slot task is not in this resume filter: {tid}",
                location="--task",
            )
        if (tid, idx) not in finished:
            raise ConfigError(
                "suite_replace_slot_missing",
                f"no finished slot {tid}[{idx}] to replace",
                location="--replace-slot",
            )
    old_fp = old_summary.get("config_fingerprint")
    if not isinstance(old_fp, str) or not old_fp.strip():
        return
    fp_rows = [{"task_id": a.get("task_id"), "run_id": a.get("run_id")} for a in existing]
    new_cfg = collect_suite_config(
        plan.dataset_root,
        fp_rows,
        overrides=overrides,
        task_ids=list(plan.task_ids),
        profiles_path=profiles_path,
    )
    new_fp = new_cfg.get("config_fingerprint")
    if str(new_fp or "") != old_fp:
        raise ConfigError(
            "suite_replace_fingerprint_mismatch",
            "replace-slot requires the same config_fingerprint / job overlay",
            location="--profiles",
        )


async def execute_suite_run(
    plan: SuitePlan,
    *,
    overrides: dict[str, Any] | None = None,
    run_fn: Callable[..., Awaitable[tuple[int, Any]]] | None = None,
    profiles_path: Path | str | None = None,
    resume: bool = False,
    replace_slots: set[tuple[str, int]] | None = None,
    on_progress: ProgressCallback | None = None,
    keep_workspace: bool = False,
    keep_vendor_raw: bool = False,
) -> dict[str, Any]:
    """Execute planned task×attempt units with a concurrency pool; write summary.

    When ``resume=True``, load existing attempts for ``plan.suite_run_id``, skip
    units that already finished a real run, **append** new attempts (including
    re-runs of suite-cancel placeholders), and recompute metrics.
    Real finished attempt rows are never rewritten; cancel placeholders are
    dropped when their slot is re-executed.

    ``replace_slots`` (named finished slots only) re-runs those keys even when
    they already have a real result. The outgoing current is pushed onto that
    slot's ``previous[]``; metrics use the new current only.

    Cancel (#47 D4): if ``suite-runs/<id>/cancel.requested`` appears, no new units
    start; in-flight units finish; remaining planned units get cancelled rows.
    Resume without replace-slot clears a prior cancel request so scheduling can
    proceed. Replace-slot refuses an unsettled suite.
    """
    reset_inflight_metrics()
    runner = run_fn or build_run_attempt()
    suite_dir_for(plan).mkdir(parents=True, exist_ok=True)

    replace = {(str(t), int(i)) for t, i in (replace_slots or set()) if str(t)}
    if replace and not resume:
        raise ConfigError(
            "suite_replace_requires_resume",
            "replace-slot requires --resume-suite",
            location="--replace-slot",
        )

    existing: list[dict[str, Any]] = []
    old_summary: dict[str, Any] | None = None
    if resume:
        if replace:
            if not suite_is_settled(plan.dataset_root, plan.suite_run_id):
                raise ConfigError(
                    "suite_in_progress",
                    "cannot replace a slot while the suite is in progress "
                    "or cancel.requested is set",
                    location=str(suite_dir_for(plan)),
                )
        else:
            # Allow re-scheduling after a previous cancel.
            clear_suite_cancel(plan.dataset_root, plan.suite_run_id)
        old_summary = load_suite_summary(plan.dataset_root, plan.suite_run_id)
        raw_attempts = old_summary.get("attempts")
        if isinstance(raw_attempts, list) and raw_attempts:
            existing = [dict(a) for a in raw_attempts if isinstance(a, Mapping)]
        else:
            legacy_tasks = old_summary.get("tasks")
            if isinstance(legacy_tasks, list):
                existing = flatten_legacy_tasks_as_attempts(
                    [t for t in legacy_tasks if isinstance(t, Mapping)]
                )
        if replace:
            _assert_replace_slots(plan, existing, old_summary, replace, overrides, profiles_path)

    done_keys = _existing_attempt_keys(existing)
    if replace:
        done_keys -= replace
    units = planned_units(plan)
    for slot in replace:
        if slot[0] in plan.task_ids and slot not in units:
            units.append(slot)
    todo = [(tid, idx) for tid, idx in units if (tid, idx) not in done_keys]
    total_units = max(len(units), len(todo) + len(done_keys & set(units)))
    # Progress: completed existing + in-flight bookkeeping.
    completed_count = len(done_keys & set(units)) if resume else 0
    cancelled = False
    new_results: list[dict[str, Any]] = []
    skipped_cancelled: list[dict[str, Any]] = []

    def _emit(event: dict[str, Any]) -> None:
        if on_progress is not None:
            with contextlib.suppress(Exception):
                on_progress(event)

    # ``created_at`` locks on the first write of this suite (resume keeps the
    # original) and every later rewrite — live or final — reuses it.
    created_at_cell: list[str] = []
    if resume and isinstance(old_summary, dict):
        prior_created = old_summary.get("created_at")
        if isinstance(prior_created, str) and prior_created.strip():
            created_at_cell.append(prior_created.strip())

    def _write_live_summary(status: str) -> None:
        """Rewrite summary.json from settled attempts (live observational view)."""
        settled = [a for a in existing if not _is_cancelled_placeholder(a)] + list(new_results)
        if not created_at_cell:
            created_at_cell.append(datetime.now(UTC).isoformat().replace("+00:00", "Z"))
        _write_summary(
            plan,
            _live_summary(plan, settled, created_at=created_at_cell[0], status=status),
        )

    _write_suite_progress(
        plan,
        done=completed_count,
        total=total_units,
        running=[],
        status="running" if todo else "complete",
    )
    _write_live_summary("running" if todo else "complete")
    _emit(
        {
            "type": "suite_start",
            "suite_run_id": plan.suite_run_id,
            "done": completed_count,
            "total": total_units,
            "todo": len(todo),
        }
    )

    # Worker pool: claim units by index so cancel can stop scheduling new work.
    # Pool size alone caps concurrency (no nested semaphore).
    todo_list = list(todo)
    claim_index = 0
    claim_lock = asyncio.Lock()
    worker_n = min(plan.max_concurrent_tasks, max(1, len(todo_list))) if todo_list else 0

    progress_lock = asyncio.Lock()
    inflight_labels: dict[tuple[str, int], str] = {}

    def _cancelled_row(tid: str, idx: int) -> dict[str, Any]:
        return {
            "task_id": tid,
            "attempt_index": idx,
            "exit_code": 2,
            "status": "ERROR",
            "score": None,
            "metrics": {},
            "run_id": None,
            "digest": None,
            "error": "suite_cancelled",
            "phase_timing": None,
            "duration": None,
            "phase": "cancelled",
        }

    def _running_snapshot() -> list[dict[str, Any]]:
        return [
            {"task_id": t, "attempt_index": i, "phase": ph}
            for (t, i), ph in inflight_labels.items()
        ]

    async def _worker() -> None:
        nonlocal completed_count, cancelled, claim_index
        while True:
            if is_suite_cancel_requested(plan.dataset_root, plan.suite_run_id):
                cancelled = True
                return
            async with claim_lock:
                if claim_index >= len(todo_list):
                    return
                tid, idx = todo_list[claim_index]
                claim_index += 1
            # Re-check after claim: do not start new work once cancel is requested.
            if is_suite_cancel_requested(plan.dataset_root, plan.suite_run_id):
                cancelled = True
                async with progress_lock:
                    skipped_cancelled.append(_cancelled_row(tid, idx))
                    completed_count += 1
                continue

            async with progress_lock:
                inflight_labels[(tid, idx)] = "running"
                _write_suite_progress(
                    plan,
                    done=completed_count,
                    total=total_units,
                    running=_running_snapshot(),
                )
                _emit(
                    {
                        "type": "unit_start",
                        "task_id": tid,
                        "attempt_index": idx,
                        "done": completed_count,
                        "total": total_units,
                        "running": list(inflight_labels.keys()),
                    }
                )

            row = await _run_one(
                plan,
                tid,
                idx,
                overrides=overrides,
                run_fn=runner,
                profiles_path=profiles_path,
                keep_workspace=keep_workspace,
                keep_vendor_raw=keep_vendor_raw,
                on_phase=_phase_forwarder(on_progress, tid, idx),
            )
            async with progress_lock:
                new_results.append(row)
                inflight_labels.pop((tid, idx), None)
                completed_count += 1
                cancel_now = is_suite_cancel_requested(plan.dataset_root, plan.suite_run_id)
                if cancel_now:
                    cancelled = True
                    st = "cancelling"
                elif claim_index < len(todo_list) or inflight_labels:
                    st = "running"
                else:
                    st = "complete"

                _write_suite_progress(
                    plan,
                    done=completed_count,
                    total=total_units,
                    running=_running_snapshot(),
                    status=st,
                )
                _write_live_summary(st)
                _emit(
                    {
                        "type": "unit_done",
                        "task_id": tid,
                        "attempt_index": idx,
                        "status": row.get("status"),
                        "done": completed_count,
                        "total": total_units,
                        "duration": row.get("duration"),
                    }
                )

    if worker_n:
        await asyncio.gather(*[asyncio.create_task(_worker()) for _ in range(worker_n)])

    # Units never claimed because of cancel → synthetic cancelled rows.
    async with claim_lock:
        remaining = todo_list[claim_index:]
    if remaining:
        cancelled = True
        for tid, idx in remaining:
            skipped_cancelled.append(_cancelled_row(tid, idx))
            completed_count += 1
    if skipped_cancelled:
        new_results.extend(skipped_cancelled)

    if replace and new_results:
        replaced_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        outgoing = {slot_key(row): row for row in existing if slot_key(row) in replace}
        for row in new_results:
            old_row = outgoing.get(slot_key(row))
            if old_row is None:
                continue
            row["previous"] = extend_slot_previous(old_row, replaced_at=replaced_at)

    # Merge: keep real finished rows; drop cancel placeholders for slots we
    # re-ran (or re-cancelled). Never mutate real finished attempt payloads.
    new_keys: set[tuple[str, int]] = set()
    for r in new_results:
        tid = str(r.get("task_id") or "")
        idx = r.get("attempt_index")
        if not tid:
            continue
        if not isinstance(idx, int) or isinstance(idx, bool):
            idx = 0
        new_keys.add((tid, idx))

    def _keep_existing_row(row: Mapping[str, Any]) -> bool:
        tid = str(row.get("task_id") or "")
        idx = row.get("attempt_index")
        if not isinstance(idx, int) or isinstance(idx, bool):
            idx = 0
        key = (tid, idx)
        # Slot re-executed this session → drop old placeholder / stale row.
        return key not in new_keys

    attempts = list(existing) + new_results
    if resume and plan.task_ids:
        planned_set = set(plan.task_ids)
        # Sibling tasks outside this resume filter stay as-is.
        kept_other = [a for a in existing if str(a.get("task_id") or "") not in planned_set]
        planned_existing = [
            a
            for a in existing
            if str(a.get("task_id") or "") in planned_set and _keep_existing_row(a)
        ]
        attempts = kept_other + planned_existing + new_results
    elif new_keys:
        attempts = [a for a in existing if _keep_existing_row(a)] + new_results

    # Union task_ids for summary when resume brings siblings.
    if resume:
        all_ids: list[str] = []
        seen: set[str] = set()
        for tid in plan.task_ids:
            if tid not in seen:
                all_ids.append(tid)
                seen.add(tid)
        for a in attempts:
            tid = str(a.get("task_id") or "")
            if tid and tid not in seen:
                all_ids.append(tid)
                seen.add(tid)
        # Mutate a shallow copy of plan fields for summary only.
        summary_plan = SuitePlan(
            dataset_id=plan.dataset_id,
            dataset_version=plan.dataset_version,
            dataset_root=plan.dataset_root,
            task_ids=all_ids,
            max_concurrent_tasks=plan.max_concurrent_tasks,
            n_attempts=plan.n_attempts,
            suite_run_id=plan.suite_run_id,
        )
        # If other tasks had more samples, take max n_attempts for display budget.
        max_n = plan.n_attempts
        by_t: dict[str, int] = {}
        for a in attempts:
            tid = str(a.get("task_id") or "")
            by_t[tid] = by_t.get(tid, 0) + 1
        if by_t:
            max_n = max(max_n, max(by_t.values()))
        summary_plan.n_attempts = max_n
    else:
        summary_plan = plan

    summary = _build_summary(
        summary_plan,
        attempts,
        overrides=overrides,
        profiles_path=profiles_path,
        created_at=created_at_cell[0] if created_at_cell else None,
    )
    if resume:
        summary["resumed"] = True
        summary["new_attempts"] = len([r for r in new_results if r.get("phase") != "cancelled"])
        summary["skipped_attempts"] = len(done_keys & set(units))
    if cancelled or is_suite_cancel_requested(plan.dataset_root, plan.suite_run_id):
        summary["cancelled"] = True
        summary["status"] = "cancelled"
        # Prefer non-zero exit when cancelled with incomplete work.
        if summary.get("exit_code") == 0 and skipped_cancelled:
            summary["exit_code"] = 2
        _write_suite_progress(
            plan,
            done=completed_count,
            total=total_units,
            running=[],
            status="cancelled",
        )
        _emit(
            {
                "type": "suite_cancelled",
                "suite_run_id": plan.suite_run_id,
                "done": completed_count,
                "total": total_units,
                "cancelled_units": len(skipped_cancelled),
            }
        )
    else:
        summary["status"] = "complete"
        _write_suite_progress(
            plan,
            done=completed_count,
            total=total_units,
            running=[],
            status="complete",
        )
        _emit(
            {
                "type": "suite_complete",
                "suite_run_id": plan.suite_run_id,
                "done": completed_count,
                "total": total_units,
                "exit_code": summary.get("exit_code"),
            }
        )
    return _write_summary(plan, summary)
