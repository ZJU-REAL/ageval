"""RunContext and parameter view handed to a task's ``run.py``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True)
class RunScope:
    """Logical run scope visible to the task run (no host secrets)."""

    attempt_id: str
    trial_id: str
    run_id: str
    deadline_monotonic: float | None = None


class RunParameterView:
    """Read-only parameter projection (JSON-compatible)."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        self._data = MappingProxyType(dict(data))

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self._data
        for part in path.split("."):
            if not isinstance(cur, Mapping) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def require_int(self, path: str) -> int:
        val = self.get(path)
        if not isinstance(val, int) or isinstance(val, bool):
            raise KeyError(path)
        return val

    def require_str(self, path: str) -> str:
        val = self.get(path)
        if not isinstance(val, str):
            raise KeyError(path)
        return val

    def as_mapping(self) -> Mapping[str, Any]:
        return self._data

    def __getitem__(self, path: str) -> Any:
        value = self.get(path, _MISSING)
        if value is _MISSING:
            raise KeyError(path)
        return value

    def __contains__(self, path: str) -> bool:
        return self.get(path, _MISSING) is not _MISSING


_MISSING = object()


@dataclass
class RunContext:
    """What ``async def run(ctx)`` may touch.

    No box handle and no path into ``evaluation/``: the task drives its Agent
    session and writes artifacts, and that is the whole surface.
    """

    params: RunParameterView
    scope: RunScope
    workspace_root: Path
    artifact_dir: Path
    # Dataset root when known: code-path access to shared assets (not an Agent mount).
    dataset_root: Path | None = None
    # Member directory. Set for every run; Harbor's built-in runner reads instruction.md here.
    task_root: Path | None = None
    agent: Any = None
    _closed: bool = False
    _published: dict[str, Path] = field(default_factory=dict)

    def close(self) -> None:
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def published(self) -> Mapping[str, Path]:
        """Artifacts this run declared, in publish order."""
        return MappingProxyType(self._published)

    def publish_json(self, artifact_id: str, data: Mapping[str, Any]) -> Path:
        """Write declared JSON artifact under artifact_dir (task-local)."""
        import json

        if self._closed:
            raise RuntimeError("context closed")
        path = self.artifact_dir / f"{artifact_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        path.write_text(payload + "\n", encoding="utf-8")
        self._published[artifact_id] = path
        return path

    def publish_file(self, artifact_id: str, source: Path) -> Path:
        if self._closed:
            raise RuntimeError("context closed")
        dest = self.artifact_dir / source.name
        dest.write_bytes(source.read_bytes())
        self._published[artifact_id] = dest
        return dest

    def publish_tree(self, artifact_id: str, source: Path) -> Path:
        """Register a workspace tree. Copy and exclude stay on Runtime harvest."""
        if self._closed:
            raise RuntimeError("context closed")
        path = Path(source)
        self._published[artifact_id] = path
        return path
