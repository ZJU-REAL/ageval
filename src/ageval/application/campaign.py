"""Campaign / matrix expansion (v0.11) — foreground serial Trials."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ageval.application.composition import build_run_attempt
from ageval.config.errors import ConfigError
from ageval.evidence.locators import campaign_locator
from ageval.model.errors import ModelConfigError


@dataclass(frozen=True, slots=True)
class MatrixAxis:
    pointer: str
    values: tuple[Any, ...]


def expand_matrix(axes: list[MatrixAxis]) -> list[dict[str, Any]]:
    """Deterministic cartesian expansion; empty axes → single empty variant."""
    variants: list[dict[str, Any]] = [{}]
    for axis in axes:
        if not axis.values:
            raise ConfigError("campaign_matrix_empty_axis", f"empty axis {axis.pointer}")
        next_variants: list[dict[str, Any]] = []
        for base in variants:
            for val in axis.values:
                item = dict(base)
                item[axis.pointer] = val
                next_variants.append(item)
        variants = next_variants
    # Stable order by JSON of pointer/value pairs
    return sorted(variants, key=lambda d: json.dumps(d, sort_keys=True, default=str))


def parse_matrix_arg(raw: str) -> MatrixAxis:
    """Parse ``/parameters/x=[1,2]`` or ``/agent_profiles/<role>/model/id=[…]``."""
    if "=" not in raw:
        raise ConfigError("campaign_matrix_invalid", "matrix must be pointer=json-array")
    pointer, _, arr = raw.partition("=")
    if not pointer.startswith("/"):
        raise ConfigError("campaign_matrix_invalid", "pointer must start with /")
    # parameters/* and binding axes (/agent_profiles/<role>/…)
    from ageval.config.overrides import is_allowlisted_override_pointer

    if not is_allowlisted_override_pointer(pointer):
        raise ConfigError(
            "campaign_matrix_pointer_unsupported",
            f"unsupported matrix pointer: {pointer}",
        )
    try:
        values = json.loads(arr)
    except json.JSONDecodeError as exc:
        raise ConfigError("campaign_matrix_invalid", "matrix values must be JSON") from exc
    if not isinstance(values, list):
        raise ConfigError("campaign_matrix_invalid", "matrix values must be a JSON array")
    return MatrixAxis(pointer=pointer, values=tuple(values))


async def run_campaign(
    package_root: Path,
    task_ids: Sequence[str] | str,
    *,
    matrix_args: list[str],
    profiles_path: Path | str | None = None,
    keep_vendor_raw: bool = False,
) -> dict[str, Any]:
    """Run every (task, variant) cell serially through the production Attempt.

    One cell that cannot even lock is one failed cell: the others still run and
    still keep their results. There is no second lifecycle here — each cell is
    an ordinary ``ageval run``.
    """
    from ageval.registry.resolve import resolve_dataset_root

    dataset_root = resolve_dataset_root(package_root)
    tasks = [task_ids] if isinstance(task_ids, str) else list(task_ids)
    variants = expand_matrix([parse_matrix_arg(arg) for arg in matrix_args])
    cells = [(task, variant) for task in tasks for variant in (variants or [{}])]

    trials: list[dict[str, Any]] = []
    dataset_id = ""
    for index, (task_id, variant) in enumerate(cells):
        row: dict[str, Any] = {
            "trial_index": index,
            "task_id": task_id,
            "variant": variant,
        }
        try:
            code, result = await build_run_attempt()(
                dataset_root,
                task_id,
                overrides=variant or None,
                profiles_path=profiles_path,
                keep_vendor_raw=keep_vendor_raw,
            )
        except (ConfigError, ModelConfigError) as exc:
            row.update({"exit_code": 2, "status": "ERROR", "error": str(exc)})
            trials.append(row)
            continue
        dataset_id = dataset_id or result.as_dict().get("dataset_id") or dataset_id
        row.update(
            {
                "exit_code": code,
                "status": result.status,
                "score": result.score,
                "evidence_path": _portable(result, dataset_root),
                "logs": _portable(result, dataset_root),
            }
        )
        trials.append(row)

    summary: dict[str, Any] = {
        "campaign": True,
        "dataset_id": dataset_id,
        "task_ids": tasks,
        "trial_count": len(trials),
        "trials": trials,
        "all_pass": bool(trials) and all(t.get("status") == "PASS" for t in trials),
    }
    summary["summary_path"] = _write_summary(dataset_root, tasks, summary)
    return summary


def _portable(result: Any, dataset_root: Path) -> str | None:
    """Never let an absolute host path into a campaign row."""
    from ageval.evidence.locators import portable_run_locator

    for raw in (result.evidence_path, result.logs):
        if raw:
            return portable_run_locator(raw, dataset_root=dataset_root)
    return None


def _write_summary(dataset_root: Path, tasks: Sequence[str], summary: dict[str, Any]) -> str:
    campaigns = dataset_root / ".ageval" / "campaigns"
    campaigns.mkdir(parents=True, exist_ok=True)
    name = "-".join(tasks) if len(tasks) <= 3 else f"{len(tasks)}-tasks"
    out = campaigns / f"summary_{name}_{summary['trial_count']}.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(out)
    try:
        return out.relative_to(dataset_root.resolve()).as_posix()
    except ValueError:
        return campaign_locator(out.name)
