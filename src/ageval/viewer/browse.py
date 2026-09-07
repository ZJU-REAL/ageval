"""Dataset open helpers and copyable CLI strings for the local viewer.

Jobs UI is the product surface; this module does not expose package file trees.
All access stays under the opened Dataset root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ageval.application.local_jobs.listing import commands_for as commands_for
from ageval.config.dataset import list_tasks, load_dataset_manifest
from ageval.registry.resolve import resolve_dataset_root


def open_dataset(dataset_ref: str | Path) -> Path:
    """Resolve and validate a Dataset root for viewing."""
    return resolve_dataset_root(dataset_ref)


def dataset_overview(root: Path) -> dict[str, Any]:
    man = load_dataset_manifest(root)
    task_ids = list_tasks(root, manifest=man)
    return {
        "dataset_id": man.dataset_id,
        "version": man.version,
        "description": man.description,
        "tasks_root": man.tasks_root,
        "task_ids": task_ids,
        "task_count": len(task_ids),
        "root": str(root),
    }
