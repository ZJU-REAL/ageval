"""Public ``ageval prepare`` use case: resolve, then run dataset preparation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def prepare_dataset_command(
    package: str | Path,
    *,
    allow_prepare: bool = False,
    notify: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Resolve *package* and prepare it; return the operator summary."""
    from ageval.config.prepare import prepare_dataset
    from ageval.registry.resolve import resolve_dataset_root

    root = resolve_dataset_root(package)

    def _notify(script: str, dataset_id: str) -> None:
        if notify is not None:
            notify(script, dataset_id)

    report = prepare_dataset(root, allow_prepare=allow_prepare, on_prepare_script=_notify)
    return {"ok": True, "dataset_root": str(root), **report.as_dict()}
