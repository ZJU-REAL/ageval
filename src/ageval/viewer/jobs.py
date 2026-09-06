"""HTTP-facing local Jobs surface: a thin forward to ``application.local_jobs``.

Listing rules and row assembly live in ``application.local_jobs.listing``.
This module keeps the public function names the HTTP server and the trials UI
import, plus the projection helpers trials reads (re-exported from listing).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ageval.application.composition import build_local_jobs_commands
from ageval.application.local_jobs.listing import (
    _duration_label as _duration_label,
)
from ageval.application.local_jobs.listing import (
    _environment_kind as _environment_kind,
)
from ageval.application.local_jobs.listing import (
    _phase_timing as _phase_timing,
)
from ageval.application.local_jobs.listing import (
    _started_at as _started_at,
)
from ageval.application.local_jobs.listing import (
    _started_from_run_dir as _started_from_run_dir,
)


def list_jobs(dataset_root: Path) -> dict[str, Any]:
    return build_local_jobs_commands().list_jobs(dataset_root)


def get_job(dataset_root: Path, job_id: str) -> dict[str, Any]:
    return build_local_jobs_commands().get_job(dataset_root, job_id)


def get_job_task(dataset_root: Path, job_id: str, task_id: str) -> dict[str, Any]:
    return build_local_jobs_commands().get_job_task(dataset_root, job_id, task_id)


def job_overlay_mapping(dataset_root: Path, job_id: str) -> dict[str, Any] | None:
    return build_local_jobs_commands().job_overlay_mapping(dataset_root, job_id)
