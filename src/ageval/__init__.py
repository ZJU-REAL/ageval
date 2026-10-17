"""ageval — agent evaluation runtime.

Lock a dataset, run one Attempt through the five phases, and bind PASS only
from an independent evaluator. CLI: ``ageval``.
"""

from __future__ import annotations

from pathlib import Path


def _load_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("ageval-cli")
    except PackageNotFoundError:
        # Editable / source tree: repo-root VERSION (src/ageval/__init__.py → parents[2]).
        version_file = Path(__file__).resolve().parents[2] / "VERSION"
        if version_file.is_file():
            return version_file.read_text(encoding="utf-8").strip()
        return "0.0.0"


__version__ = _load_version()
