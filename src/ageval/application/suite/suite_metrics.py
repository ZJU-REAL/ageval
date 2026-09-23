"""Suite-level metric aggregation from per-task / per-attempt evaluator Results.

Rules (MVP, fixed — not package-configurable):

- ``pass_rate`` = count(status == PASS) / n_tasks  (legacy, one row per task)
- ``mean_score`` = mean of per-task scores; missing / non-numeric / ERROR
  treated as **0.0** (Harbor-like default for absent reward)
- FAIL with numeric score keeps that score (typically 0.0)
- **No suite-level PASS** — PASS remains per-task evaluator authority only

Multi-attempt (#47):

- Always-k produces *n* independent Attempt samples per task.
- **pass@k** = unbiased estimator ``1 - C(n-c, k) / C(n, k)`` (Chen / Harbor).
- **pass^k** = ``(c/n)^k`` (all-k succeed; ageval addition, not Harbor).
- Suite / dataset score for a metric = **mean over tasks** that have enough
  samples for that k (tasks with ``n < k`` are omitted from that k's mean).
- These metrics are job summary only — **not** package identity / fingerprint.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import comb
from typing import Any

# Documented default for absent scores (Harbor reward-missing → 0).
MISSING_SCORE_AS = 0.0


def _normalize_status(raw: object) -> str:
    return str(raw or "").strip().upper()


def _numeric_score_or_none(raw: object) -> float | None:
    """Return a real number score, or None if missing / bool / non-numeric.

    ``bool`` is a subclass of ``int`` in Python; treat it as non-numeric so
    ``True``/``False`` never become 1.0/0.0 by accident.
    """
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw)


def _score_value(row: Mapping[str, Any]) -> float:
    """Per-task score contribution for mean_score.

    Missing / non-numeric → ``MISSING_SCORE_AS`` (0.0).
    Status ERROR also forces 0.0 even if a score field is present.
    """
    status = _normalize_status(row.get("status"))
    if status == "ERROR":
        return MISSING_SCORE_AS
    value = _numeric_score_or_none(row.get("score"))
    return MISSING_SCORE_AS if value is None else value


def aggregate_task_metrics(task_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate per-task result rows into stable suite metrics.

    Parameters
    ----------
    task_rows:
        Rows shaped like suite summary ``tasks[]`` entries
        (at least ``status``; optional ``score``).

    Returns
    -------
    dict
        ``pass_rate``, ``mean_score``, ``n_tasks``, ``n_pass``,
        ``n_fail``, ``n_error``, ``missing_score_as``.
    """
    n = len(task_rows)
    n_pass = 0
    n_fail = 0
    n_error = 0
    scores: list[float] = []

    for row in task_rows:
        st = _normalize_status(row.get("status"))
        if st == "PASS":
            n_pass += 1
        elif st == "FAIL":
            n_fail += 1
        else:
            # ERROR, SKIPPED, unknown → error bucket for rates; score → 0
            n_error += 1
        scores.append(_score_value(row))

    pass_rate = (n_pass / n) if n else 0.0
    mean_score = (sum(scores) / n) if n else 0.0

    return {
        "pass_rate": pass_rate,
        "mean_score": mean_score,
        "n_tasks": n,
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_error": n_error,
        "missing_score_as": MISSING_SCORE_AS,
    }


def slot_key(row: Mapping[str, Any]) -> tuple[str, int]:
    """Scoring-slot identity: ``(task_id, attempt_index)`` (missing index → 0)."""
    tid = str(row.get("task_id") or "")
    idx = row.get("attempt_index")
    if not isinstance(idx, int) or isinstance(idx, bool):
        idx = 0
    return tid, idx


def attempt_started_at(row: Mapping[str, Any]) -> str | None:
    """Per-Attempt start, not suite replace time."""
    for key in ("started_at", "started"):
        raw = row.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    timing = row.get("phase_timing")
    if isinstance(timing, Mapping):
        raw = timing.get("started_at")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def previous_entry(row: Mapping[str, Any], *, replaced_at: str) -> dict[str, Any]:
    """Slim superseded snapshot. Old Attempt identity/score stay immutable."""
    _tid, idx = slot_key(row)
    out: dict[str, Any] = {
        "run_id": row.get("run_id"),
        "status": _normalize_status(row.get("status")) or None,
        "score": _numeric_score_or_none(row.get("score")),
        "attempt_index": idx,
        "replaced_at": replaced_at,
    }
    started = attempt_started_at(row)
    if started:
        out["started_at"] = started
    return out


def extend_slot_previous(old_row: Mapping[str, Any], *, replaced_at: str) -> list[dict[str, Any]]:
    """Oldest → newest superseded: keep prior chain, then the outgoing current."""
    chain: list[dict[str, Any]] = []
    raw = old_row.get("previous")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, Mapping):
                chain.append(dict(item))
    chain.append(previous_entry(old_row, replaced_at=replaced_at))
    return chain


def previous_from_attempts(attempt_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Flatten per-slot ``previous[]`` in attempt_index order."""
    ordered = sorted(attempt_rows, key=lambda r: slot_key(r)[1])
    out: list[dict[str, Any]] = []
    for row in ordered:
        raw = row.get("previous")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, Mapping):
                out.append(dict(item))
    return out


def _reason_for_run(
    row: Mapping[str, Any],
    attempts: Sequence[Mapping[str, Any]],
    run_id: object,
) -> tuple[object, object]:
    """error and limit on the attempt ``run_id`` points at."""
    error = row.get("error")
    limit = row.get("limit")
    wanted = str(run_id or "")
    if not wanted:
        return error, limit
    for attempt in attempts:
        if str(attempt.get("run_id") or "") != wanted:
            continue
        if "error" in attempt:
            error = attempt.get("error")
        if "limit" in attempt:
            limit = attempt.get("limit")
        break
    return error, limit


def task_refs_for_summary(
    task_rows: Sequence[Mapping[str, Any]],
    *,
    attempts: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Minimal per-task references for suite/job result rows (leaderboard).

    When *attempts* is provided (or a task row nests ``attempts``), each ref
    may include ``n``, ``c``, and ``attempt_run_ids`` for multi-attempt audit
    and ``--with-attempts`` upload completeness (#60 A3). ``previous[]`` is the
    superseded chain (audit only; not in metrics).
    """
    by_task: dict[str, list[Mapping[str, Any]]] = {}
    if attempts is not None:
        by_task = group_attempts_by_task(attempts)

    refs: list[dict[str, Any]] = []
    for row in task_rows:
        tid = str(row.get("task_id") or "")
        ref: dict[str, Any] = {
            "task_id": row.get("task_id"),
            "status": _normalize_status(row.get("status")) or None,
            "score": _numeric_score_or_none(row.get("score")),
            "run_id": row.get("run_id"),
        }
        n_val = row.get("n")
        c_val = row.get("c")
        attempt_run_ids: list[str] = []

        # Nested attempts on the task row (legacy / materialised shapes).
        nested = row.get("attempts")
        nested_rows: list[Mapping[str, Any]] = []
        if isinstance(nested, list) and nested:
            nested_rows = [a for a in nested if isinstance(a, Mapping)]
        elif tid and tid in by_task:
            nested_rows = list(by_task[tid])

        if nested_rows:
            nested_rows = sorted(nested_rows, key=lambda r: slot_key(r)[1])
            n_from, c_from = count_passes(nested_rows)
            if n_val is None:
                n_val = n_from
            if c_val is None:
                c_val = c_from
            for a in nested_rows:
                rid = a.get("run_id")
                if rid is None:
                    continue
                text = str(rid).strip()
                if text and text not in attempt_run_ids:
                    attempt_run_ids.append(text)

        # Explicit attempt_run_ids on the task / prior ref.
        explicit = row.get("attempt_run_ids")
        if isinstance(explicit, list):
            for rid in explicit:
                if rid is None:
                    continue
                text = str(rid).strip()
                if text and text not in attempt_run_ids:
                    attempt_run_ids.append(text)

        if n_val is not None:
            ref["n"] = n_val
        if c_val is not None:
            ref["c"] = c_val
        if attempt_run_ids:
            ref["attempt_run_ids"] = attempt_run_ids
            # Prefer primary run_id when missing: PASS attempt, else first.
            if not ref.get("run_id"):
                ref["run_id"] = attempt_run_ids[0]
        history = previous_from_attempts(nested_rows)
        if not history:
            raw_prev = row.get("previous")
            if isinstance(raw_prev, list):
                history = [dict(item) for item in raw_prev if isinstance(item, Mapping)]
        if history:
            ref["previous"] = history
        error, limit = _reason_for_run(row, nested_rows, ref.get("run_id"))
        ref["error"] = error
        ref["limit"] = limit
        refs.append(ref)
    return refs


# ---------------------------------------------------------------------------
# Multi-attempt: pass@k / pass^k (#47)
# ---------------------------------------------------------------------------


def pass_at_k(*, n: int, c: int, k: int) -> float | None:
    """Unbiased pass@k estimator (Chen et al.; Harbor).

    ``1 - C(n-c, k) / C(n, k)`` when ``n >= k``; else ``None`` (incomplete).
    """
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        return None
    if not isinstance(c, int) or isinstance(c, bool) or c < 0 or c > n:
        return None
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        return None
    if n < k:
        return None
    if n - c < k:
        return 1.0
    return 1.0 - (comb(n - c, k) / comb(n, k))


def pass_power_k(*, n: int, c: int, k: int) -> float | None:
    """pass^k estimator: probability all *k* independent attempts succeed.

    Uses ``(c/n)^k``. Returns ``None`` when ``n < 1`` or *k* invalid.
    Does not require ``n >= k`` (with Always-k, n is usually the sample budget).
    """
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        return None
    if not isinstance(c, int) or isinstance(c, bool) or c < 0 or c > n:
        return None
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        return None
    return (c / n) ** k


def default_k_values(n_samples: int) -> list[int]:
    """Harbor-like k set: 1, powers of 2, steps of 5, and *n_samples* itself."""
    if not isinstance(n_samples, int) or isinstance(n_samples, bool) or n_samples < 1:
        return []
    ks: set[int] = {1, n_samples}
    p = 2
    while p <= n_samples:
        ks.add(p)
        p *= 2
    for m in range(5, n_samples + 1, 5):
        ks.add(m)
    return sorted(ks)


def count_passes(attempt_rows: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """Return ``(n, c)`` where *c* counts attempts with status PASS."""
    n = len(attempt_rows)
    c = sum(1 for row in attempt_rows if _normalize_status(row.get("status")) == "PASS")
    return n, c


def group_attempts_by_task(
    attempt_rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    """Group attempt rows by ``task_id`` (stable insertion order of first seen)."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in attempt_rows:
        tid = str(row.get("task_id") or "")
        if tid not in groups:
            groups[tid] = []
        groups[tid].append(row)
    return groups


def _metrics_map_for_nc(
    n: int,
    c: int,
    k_values: Sequence[int],
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    pass_at: dict[str, float | None] = {}
    pass_pow: dict[str, float | None] = {}
    for k in k_values:
        key = str(k)
        pass_at[key] = pass_at_k(n=n, c=c, k=k)
        pass_pow[key] = pass_power_k(n=n, c=c, k=k)
    return pass_at, pass_pow


def rollup_task_from_attempts(
    task_id: str,
    attempt_rows: Sequence[Mapping[str, Any]],
    *,
    k_values: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Collapse attempt samples for one task into a summary row + k-metrics."""
    ordered = sorted(
        attempt_rows,
        key=lambda r: (
            int(r["attempt_index"])
            if isinstance(r.get("attempt_index"), int)
            and not isinstance(r.get("attempt_index"), bool)
            else 10**9,
            str(r.get("run_id") or ""),
        ),
    )
    n, c = count_passes(ordered)
    ks = list(k_values) if k_values is not None else default_k_values(n if n else 1)
    pass_at, pass_pow = _metrics_map_for_nc(n, c, ks)

    # Rolled status: any PASS → PASS; else any FAIL → FAIL; else ERROR.
    statuses = [_normalize_status(r.get("status")) for r in ordered]
    if any(s == "PASS" for s in statuses):
        status = "PASS"
    elif any(s == "FAIL" for s in statuses):
        status = "FAIL"
    elif any(s == "ERROR" for s in statuses) or not statuses:
        status = "ERROR"
    else:
        status = statuses[-1]

    # Representative score: mean of attempt scores (ERROR→0), Harbor-like.
    scores = [_score_value(r) for r in ordered]
    mean_score = (sum(scores) / len(scores)) if scores else MISSING_SCORE_AS
    # Prefer a PASS attempt's run_id for task_refs; else first.
    run_id = None
    for r in ordered:
        if _normalize_status(r.get("status")) == "PASS" and r.get("run_id"):
            run_id = r.get("run_id")
            break
    if run_id is None and ordered:
        run_id = ordered[0].get("run_id")

    return {
        "task_id": task_id,
        "status": status,
        "score": mean_score,
        "n": n,
        "c": c,
        "run_id": run_id,
        "attempt_indices": [
            r.get("attempt_index") for r in ordered if r.get("attempt_index") is not None
        ],
        "pass_at_k": pass_at,
        "pass_power_k": pass_pow,
        "attempts": list(ordered),
    }


def aggregate_k_metrics(
    attempt_rows: Sequence[Mapping[str, Any]],
    *,
    task_ids: Sequence[str] | None = None,
    n_attempts: int | None = None,
    k_values: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Compute per-task and suite-mean pass@k / pass^k from attempt samples.

    Tasks with ``n < k`` are **omitted** from that *k*'s suite mean (incomplete).
    Metrics never enter ``config_fingerprint`` — caller places them under
    ``metrics`` / job summary only.
    """
    groups = group_attempts_by_task(attempt_rows)
    ordered_ids: list[str]
    if task_ids is not None:
        ordered_ids = [str(t) for t in task_ids]
        for tid in groups:
            if tid not in ordered_ids:
                ordered_ids.append(tid)
    else:
        ordered_ids = list(groups.keys())

    sample_budget = n_attempts
    if sample_budget is None:
        sample_budget = max((len(groups[t]) for t in ordered_ids if t in groups), default=1)
    if sample_budget < 1:
        sample_budget = 1

    ks = list(k_values) if k_values is not None else default_k_values(sample_budget)

    task_rows: list[dict[str, Any]] = []
    for tid in ordered_ids:
        rows = groups.get(tid, [])
        task_rows.append(rollup_task_from_attempts(tid, rows, k_values=ks))

    # Suite mean per k: mean over tasks where the value is not None.
    suite_pass_at: dict[str, Any] = {}
    suite_pass_pow: dict[str, Any] = {}
    for k in ks:
        key = str(k)
        at_vals = [
            float(t["pass_at_k"][key])
            for t in task_rows
            if t.get("pass_at_k", {}).get(key) is not None
        ]
        pow_vals = [
            float(t["pass_power_k"][key])
            for t in task_rows
            if t.get("pass_power_k", {}).get(key) is not None
        ]
        suite_pass_at[key] = {
            "value": (sum(at_vals) / len(at_vals)) if at_vals else None,
            "n_tasks": len(at_vals),
            "incomplete_tasks": len(task_rows) - len(at_vals),
        }
        suite_pass_pow[key] = {
            "value": (sum(pow_vals) / len(pow_vals)) if pow_vals else None,
            "n_tasks": len(pow_vals),
            "incomplete_tasks": len(task_rows) - len(pow_vals),
        }

    legacy = aggregate_task_metrics(task_rows)
    return {
        **legacy,
        "n_attempts": sample_budget,
        "k_values": list(ks),
        "pass_at_k": suite_pass_at,
        "pass_power_k": suite_pass_pow,
        "per_task": [
            {
                "task_id": t["task_id"],
                "n": t["n"],
                "c": t["c"],
                "status": t["status"],
                "pass_at_k": t["pass_at_k"],
                "pass_power_k": t["pass_power_k"],
            }
            for t in task_rows
        ],
        "task_rows": task_rows,
    }


def flatten_legacy_tasks_as_attempts(
    task_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Convert pre-#47 summary ``tasks[]`` (one row per task) into attempt rows."""
    out: list[dict[str, Any]] = []
    for row in task_rows:
        # Already multi-attempt nested?
        nested = row.get("attempts")
        if isinstance(nested, list) and nested:
            for a in nested:
                if isinstance(a, Mapping):
                    out.append(dict(a))
            continue
        attempt_index = row.get("attempt_index")
        if not isinstance(attempt_index, int) or isinstance(attempt_index, bool):
            attempt_index = 0
        out.append(
            {
                "task_id": row.get("task_id"),
                "attempt_index": attempt_index,
                "exit_code": row.get("exit_code"),
                "status": row.get("status"),
                "score": row.get("score"),
                "metrics": row.get("metrics") if isinstance(row.get("metrics"), dict) else {},
                "run_id": row.get("run_id"),
                "digest": row.get("digest"),
                "error": row.get("error"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Pre-upload ensure / recompute (#60 A)
# ---------------------------------------------------------------------------


def has_k_metrics(metrics: Mapping[str, Any] | None) -> bool:
    """True when metrics already carry suite-level pass@k / pass^k maps."""
    if not isinstance(metrics, Mapping):
        return False
    pass_at = metrics.get("pass_at_k")
    pass_pow = metrics.get("pass_power_k")
    if not isinstance(pass_at, dict) or not pass_at:
        return False
    return isinstance(pass_pow, dict) and bool(pass_pow)


def _int_or_none(raw: object) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def _single_sample_from_task_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """One attempt row from a rolled task summary (legacy / incomplete n without c)."""
    return {
        "task_id": row.get("task_id"),
        "attempt_index": 0,
        "status": row.get("status"),
        "score": row.get("score"),
        "run_id": row.get("run_id"),
    }


def _synthetic_attempts_from_nc(
    task_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]] | None:
    """Build attempt rows from per-task ``n``/``c`` when full attempts are absent.

    Creates *c* PASS + *(n-c)* FAIL synthetic samples so ``aggregate_k_metrics``
    can recompute pass@k without inventing suite PASS.

    Recovery rules when ``c`` is missing:

    - ``n == 1``: rolled status determines ``c`` (PASS → 1, else 0).
    - ``n > 1`` and rolled non-PASS: ``c = 0`` is sound under ageval rollup
      (any PASS would have rolled to PASS).
    - ``n > 1`` and rolled PASS: **do not** invent ``c = n`` — that would treat
      "at least one pass" as "all n passed" and inflate pass@k. Fall back to a
      single sample from rolled status so multi-k stays incomplete for that task.

    Returns ``None`` when no task has recoverable multi-attempt data (nested
    attempts or complete ``n``+``c`` / recoverable zero-pass ``n``). Caller may
    then flatten pure legacy ``tasks[]``.
    """
    any_recoverable = False
    out: list[dict[str, Any]] = []
    for row in task_rows:
        n = _int_or_none(row.get("n"))
        c = _int_or_none(row.get("c"))
        nested = row.get("attempts")
        if isinstance(nested, list) and nested:
            for a in nested:
                if isinstance(a, Mapping):
                    out.append(dict(a))
            any_recoverable = True
            continue
        if n is None or n < 1:
            # Single-sample fallback from rolled status (legacy tasks[]).
            out.append(_single_sample_from_task_row(row))
            continue
        if c is None:
            st = _normalize_status(row.get("status"))
            if n == 1:
                # Exactly one sample: c is determined by that rolled status.
                c = 1 if st == "PASS" else 0
            elif st == "PASS":
                # Multi-attempt with unknown c — omit invented multi-sample.
                out.append(_single_sample_from_task_row(row))
                continue
            else:
                # ageval rollup: no PASS ⇒ c == 0.
                c = 0
        any_recoverable = True
        c = max(0, min(c, n))
        for i in range(n):
            out.append(
                {
                    "task_id": row.get("task_id"),
                    "attempt_index": i,
                    "status": "PASS" if i < c else "FAIL",
                    "score": 1.0 if i < c else 0.0,
                    "run_id": row.get("run_id") if i == 0 else None,
                }
            )
    return out if any_recoverable else None


def metrics_payload_from_k_agg(k_agg: Mapping[str, Any]) -> dict[str, Any]:
    """Stable ``summary.metrics`` / upload shape from ``aggregate_k_metrics``."""
    return {
        "pass_rate": k_agg["pass_rate"],
        "mean_score": k_agg["mean_score"],
        "n_tasks": k_agg["n_tasks"],
        "n_pass": k_agg["n_pass"],
        "n_fail": k_agg["n_fail"],
        "n_error": k_agg["n_error"],
        "missing_score_as": k_agg["missing_score_as"],
        "n_attempts": k_agg["n_attempts"],
        "k_values": list(k_agg["k_values"]),
        "pass_at_k": k_agg["pass_at_k"],
        "pass_power_k": k_agg["pass_power_k"],
        "per_task": list(k_agg["per_task"]),
    }


def ensure_suite_metrics(
    summary: Mapping[str, Any],
    *,
    task_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return suite metrics, recomputing pass@k when missing but recoverable (#60 A2).

    Priority:

    1. Existing ``metrics`` that already include ``pass_at_k`` / ``pass_power_k``
    2. Recompute from ``summary.attempts[]`` via ``aggregate_k_metrics``
    3. Recompute from ``tasks[]`` with recoverable ``n``/``c`` (or nested attempts);
       ``n`` without ``c`` on a multi-attempt PASS does **not** invent ``c = n``
    4. Legacy single-sample / ``aggregate_task_metrics`` when multi-attempt
       samples are unrecoverable

    Does **not** write suite-level PASS. Never touches ``config_fingerprint``.
    """
    rows = list(task_rows) if task_rows is not None else []
    if not rows:
        raw_tasks = summary.get("tasks")
        if isinstance(raw_tasks, list):
            rows = [t for t in raw_tasks if isinstance(t, Mapping)]

    raw_metrics = summary.get("metrics")
    metrics: dict[str, Any] = dict(raw_metrics) if isinstance(raw_metrics, dict) else {}

    if has_k_metrics(metrics):
        # Backfill lightweight keys if older writers omitted them.
        if metrics.get("n_attempts") is None:
            top = summary.get("n_attempts")
            if isinstance(top, int) and not isinstance(top, bool) and top >= 1:
                metrics["n_attempts"] = top
        if not isinstance(metrics.get("k_values"), list):
            pass_at = metrics.get("pass_at_k")
            if isinstance(pass_at, dict) and pass_at:
                keys: list[int] = []
                for k in pass_at:
                    try:
                        keys.append(int(k))
                    except (TypeError, ValueError):
                        continue
                if keys:
                    metrics["k_values"] = sorted(keys)
        if "per_task" not in metrics and rows:
            # Optional audit surface; leave empty rather than invent wrong n/c.
            pass
        if metrics.get("pass_rate") is None and rows:
            legacy = aggregate_task_metrics(rows)
            for key in (
                "pass_rate",
                "mean_score",
                "n_tasks",
                "n_pass",
                "n_fail",
                "n_error",
                "missing_score_as",
            ):
                if metrics.get(key) is None:
                    metrics[key] = legacy[key]
        return metrics

    n_attempts = _int_or_none(summary.get("n_attempts"))
    if n_attempts is None:
        n_attempts = _int_or_none(metrics.get("n_attempts"))

    attempt_rows: list[dict[str, Any]] = []
    # True when attempts were invented from n/c or single-row status (scores may be 0/1 only).
    synthetic_attempts = False
    raw_attempts = summary.get("attempts")
    if isinstance(raw_attempts, list) and raw_attempts:
        attempt_rows = [dict(a) for a in raw_attempts if isinstance(a, Mapping)]

    if not attempt_rows and rows:
        synthetic = _synthetic_attempts_from_nc(rows)
        if synthetic is not None:
            attempt_rows = synthetic
            synthetic_attempts = True
        else:
            # Pure legacy: one sample per task from rolled status.
            attempt_rows = flatten_legacy_tasks_as_attempts(rows)
            synthetic_attempts = True

    if attempt_rows:
        task_ids = None
        raw_ids = summary.get("task_ids")
        if isinstance(raw_ids, list) and raw_ids:
            task_ids = [str(t) for t in raw_ids]
        elif rows:
            task_ids = [str(t.get("task_id") or "") for t in rows]
        k_agg = aggregate_k_metrics(
            attempt_rows,
            task_ids=task_ids,
            n_attempts=n_attempts,
        )
        recomputed = metrics_payload_from_k_agg(k_agg)
        # Prefer recomputed k maps; keep any extra observational keys already present.
        merged = dict(metrics)
        if synthetic_attempts and metrics:
            # n/c synthesis invents 0/1 scores — do not clobber real pass_rate /
            # mean_score (or counts) that a prior writer already stored.
            k_only = {
                "n_attempts": recomputed["n_attempts"],
                "k_values": recomputed["k_values"],
                "pass_at_k": recomputed["pass_at_k"],
                "pass_power_k": recomputed["pass_power_k"],
                "per_task": recomputed["per_task"],
            }
            for key, value in recomputed.items():
                if key in k_only:
                    continue
                merged.setdefault(key, value)
            merged.update(k_only)
        else:
            merged.update(recomputed)
        return merged

    if not metrics and rows:
        return aggregate_task_metrics(rows)
    if rows and metrics.get("pass_rate") is None:
        legacy = aggregate_task_metrics(rows)
        for key, value in legacy.items():
            metrics.setdefault(key, value)
    return metrics


def ensure_suite_task_refs(
    summary: Mapping[str, Any],
    *,
    task_rows: Sequence[Mapping[str, Any]] | None = None,
    existing_refs: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build / enrich task_refs with per-task n, c, attempt_run_ids when recoverable."""
    rows: list[Mapping[str, Any]]
    if task_rows is not None:
        rows = list(task_rows)
    else:
        raw_tasks = summary.get("tasks")
        if isinstance(raw_tasks, list):
            rows = [t for t in raw_tasks if isinstance(t, Mapping)]
        else:
            rows = []

    attempts_raw = summary.get("attempts")
    attempts: list[Mapping[str, Any]] | None = None
    if isinstance(attempts_raw, list) and attempts_raw:
        attempts = [a for a in attempts_raw if isinstance(a, Mapping)]

    if not rows and attempts:
        # Interrupted resume may persist attempts[] without tasks[].
        by_tid: dict[str, dict[str, Any]] = {}
        for attempt in attempts:
            tid = str(attempt.get("task_id") or "").strip()
            if not tid or tid in by_tid:
                continue
            by_tid[tid] = {
                "task_id": tid,
                "status": attempt.get("status"),
                "score": attempt.get("score"),
                "run_id": attempt.get("run_id"),
                "error": attempt.get("error"),
                "limit": attempt.get("limit"),
            }
        rows = list(by_tid.values())

    # Prefer rebuilding from tasks + attempts so n/c/run_ids stay complete.
    if rows:
        rebuilt = task_refs_for_summary(rows, attempts=attempts)
        if rebuilt:
            # If caller had richer status/score on existing_refs only, merge by task_id.
            if existing_refs:
                by_id = {
                    str(r.get("task_id") or ""): dict(r)
                    for r in existing_refs
                    if isinstance(r, Mapping)
                }
                for ref in rebuilt:
                    tid = str(ref.get("task_id") or "")
                    prior = by_id.get(tid)
                    if not prior:
                        continue
                    for key in ("status", "score", "run_id"):
                        if ref.get(key) is None and prior.get(key) is not None:
                            ref[key] = prior.get(key)
                    if ref.get("n") is None and prior.get("n") is not None:
                        ref["n"] = prior.get("n")
                    if ref.get("c") is None and prior.get("c") is not None:
                        ref["c"] = prior.get("c")
                    prior_ids = prior.get("attempt_run_ids")
                    if not ref.get("attempt_run_ids") and isinstance(prior_ids, list):
                        ref["attempt_run_ids"] = [
                            str(x).strip() for x in prior_ids if x is not None and str(x).strip()
                        ]
                    prior_prev = prior.get("previous")
                    if not ref.get("previous") and isinstance(prior_prev, list):
                        ref["previous"] = [
                            dict(item) for item in prior_prev if isinstance(item, Mapping)
                        ]
            return rebuilt

    if existing_refs is not None:
        return [dict(r) for r in existing_refs if isinstance(r, Mapping)]
    raw_refs = summary.get("task_refs")
    if isinstance(raw_refs, list):
        return [dict(r) for r in raw_refs if isinstance(r, Mapping)]
    return []
