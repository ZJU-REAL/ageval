"""Path sandboxing and evidence root resolution for viewer trials.

Evidence layout / run-dir lookup is owned by ``ageval.evidence``; this module
only adds viewer-local query parsing and path sandbox helpers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from ageval.config.errors import ConfigError
from ageval.evidence.locators import resolve_evidence_root, safe_id_segment

__all__ = [
    "parse_query",
    "resolve_evidence_root",
    "safe_under",
]


def safe_under(root: Path, relative: str) -> Path:
    """Resolve *relative* under *root*; reject traversal and escape."""
    if not relative or relative.startswith(("/", "\\")):
        raise ConfigError(
            "invalid_package",
            "path must be relative",
            location=relative or ".",
        )
    parts = Path(relative).parts
    if ".." in parts:
        raise ConfigError(
            "invalid_package",
            "path traversal rejected",
            location=relative,
        )
    root_resolved = root.resolve(strict=False)
    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ConfigError(
            "invalid_package",
            "path escapes sandbox",
            location=relative,
        ) from exc
    return candidate


# Back-compat alias used by older viewer call sites.
_safe_under = safe_under


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def parse_query(query: str) -> dict[str, str]:
    """Parse URL query string into first-value map."""
    qs = parse_qs(query or "", keep_blank_values=False)
    return {k: v[0] for k, v in qs.items() if v}


def _safe_run_id(run_id: str) -> str:
    return safe_id_segment(run_id, field="run_id")
