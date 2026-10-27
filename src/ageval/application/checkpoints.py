"""List retained checkpoints for one Attempt. Does not start an environment."""

from __future__ import annotations

from pathlib import Path

from ageval.evidence.fork_cuts import CheckpointListing, list_fork_cuts
from ageval.evidence.locators import default_runs_root


def list_checkpoints(dataset: Path | str, attempt_id: str) -> CheckpointListing:
    """Return fork classification for ``<dataset>/.ageval/runs/<attempt_id>``."""
    name = attempt_id.strip()
    if not _attempt_id_ok(name):
        return CheckpointListing(
            attempt_id=name,
            retained=False,
            error="unknown_run",
            message="attempt id must be a single directory name",
            cuts=(),
        )
    root = default_runs_root(dataset) / name
    if not root.is_dir():
        return CheckpointListing(
            attempt_id=name,
            retained=False,
            error="unknown_run",
            message="attempt directory was not found",
            cuts=(),
        )
    return list_fork_cuts(root, attempt_id=name)


def _attempt_id_ok(name: str) -> bool:
    if not name or name in {".", ".."}:
        return False
    return "/" not in name and "\\" not in name and "\x00" not in name
