"""Official Attempt base image recipe, shipped in the wheel.

``ageval run`` builds ``ageval-attempt:base`` from these files. The lookup is
this package directory, never the process cwd.
"""

from __future__ import annotations

from pathlib import Path

from ageval.plugins.paths import ageval_home

ATTEMPT_DIR = Path(__file__).resolve().parent
DEFAULT_PYTHON_VERSION = "3.12"


def official_lock_path(python_version: str | None) -> Path:
    """Where the parent records a successful official-base build."""
    if not python_version or python_version == DEFAULT_PYTHON_VERSION:
        name = "attempt-base.json"
    else:
        name = f"attempt-base-py{python_version}.json"
    return ageval_home() / "runtime-images" / name
