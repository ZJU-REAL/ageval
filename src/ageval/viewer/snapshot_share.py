"""Viewer calls for snapshot share. Registry credentials stay on this process."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ageval.application.composition import build_results_commands
from ageval.config.errors import ConfigError


def share_status(dataset_root: Path, job_id: str, *, run_id: str | None = None) -> dict[str, Any]:
    return build_results_commands().snapshot_status(
        dataset_root, suite_run_id=job_id, run_id=run_id
    )


def create_share(
    dataset_root: Path,
    job_id: str,
    *,
    run_id: str | None = None,
    live: bool = False,
) -> dict[str, Any]:
    return build_results_commands().share_snapshot(
        dataset_root,
        suite_run_id=job_id,
        run_id=run_id,
        live=live,
    )


def revoke_share(dataset_root: Path, job_id: str, *, run_id: str | None = None) -> dict[str, Any]:
    current = share_status(dataset_root, job_id, run_id=run_id)
    if not current.get("shared"):
        raise ConfigError("not_found", "snapshot share not found", location="share")
    token = str(current.get("token") or "")
    revoked = build_results_commands().revoke_snapshot(token)
    _clear_matching_sidecar(dataset_root, str(current.get("suite_run_id") or job_id), token)
    revoked["shared"] = False
    revoked["suite_run_id"] = current.get("suite_run_id")
    revoked["run_id"] = current.get("run_id") or ""
    return revoked


def _clear_matching_sidecar(dataset_root: Path, suite_run_id: str, token: str) -> None:
    from ageval.application.registry_ops.live_share import read_live_share, sidecar_path

    side = read_live_share(dataset_root, suite_run_id)
    if side is None or str(side.get("token") or "") != token:
        return
    sidecar_path(dataset_root, suite_run_id).unlink(missing_ok=True)
