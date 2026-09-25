"""Task worker entrypoint: run the task's own ``run.py`` inside the box.

The control plane never imports task modules. The parent attaches this module
through ``environment.attach_stdio`` and speaks length-prefixed JSON over the
process pipes: one launch message in, one result envelope out.

``stdout`` is claimed by that framing, so fd 1 is re-pointed at stderr before
any task code runs: a ``print`` in ``run.py`` is diagnostics, not protocol.

Usage (inside the box)::

    python -m ageval.runtime.task_worker
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import struct
import sys
import traceback
from pathlib import Path
from typing import Any


class _Frames:
    """Length-prefixed JSON over the two raw fds the parent handed us."""

    def __init__(self, read_fd: int, write_fd: int) -> None:
        self._read_fd = read_fd
        self._write_fd = write_fd

    def recv(self) -> dict[str, Any]:
        header = self._read_exact(4)
        (size,) = struct.unpack("!I", header)
        return json.loads(self._read_exact(size).decode("utf-8"))

    def send(self, obj: dict[str, Any]) -> None:
        raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload = struct.pack("!I", len(raw)) + raw
        while payload:
            payload = payload[os.write(self._write_fd, payload) :]

    def _read_exact(self, size: int) -> bytes:
        buf = b""
        while len(buf) < size:
            chunk = os.read(self._read_fd, size - len(buf))
            if not chunk:
                raise EOFError("parent closed the launch channel")
            buf += chunk
        return buf


def failure_envelope(exc: BaseException) -> dict[str, str]:
    """Title and message the parent stores. A task group is not unwrapped."""
    from ageval_sdk.errors import ScriptError

    if isinstance(exc, ScriptError):
        return {"error": exc.title, "message": exc.message}
    return {"error": type(exc).__name__, "message": str(exc)}


def _claim_stdout() -> _Frames:
    """Take fd 1 for framing and give task code stderr instead.

    A ``print`` in ``run.py`` is diagnostics, not protocol, so it must not land
    in the middle of the result envelope.
    """
    frame_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return _Frames(0, frame_fd)


def _box_dir(env_name: str) -> Path:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        raise RuntimeError(f"box did not publish {env_name}")
    return Path(raw)


def _load_entry(task_root: Path, entrypoint: str, dataset_root: Path | None) -> Any:
    """Import ``<module>.py`` from the task directory and return its function."""
    module_name, _, func_name = entrypoint.partition(":")
    if not module_name or not func_name:
        raise ValueError(f"invalid entrypoint: {entrypoint}")
    path = task_root / f"{module_name}.py"
    if not path.is_file():
        raise FileNotFoundError(f"task entry module missing: {path.name}")
    _extend_import_path(task_root, dataset_root)
    spec = importlib.util.spec_from_file_location(f"ageval_task_{module_name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, func_name)


def _extend_import_path(task_root: Path, dataset_root: Path | None) -> None:
    """Authors import ``lib.*`` (task-local) and ``shared.*`` (dataset-level)."""
    if dataset_root is not None:
        root = str(dataset_root.resolve())
        if root not in sys.path:
            sys.path.insert(0, root)
    task = str(task_root.resolve())
    if task in sys.path:
        sys.path.remove(task)
    sys.path.insert(0, task)


async def _run(frames: _Frames) -> int:
    launch = frames.recv()
    task_root = Path(launch["task_root"])
    dataset_raw = launch.get("dataset_root")
    dataset_root = Path(dataset_raw) if dataset_raw else None
    attempt_id = str(launch["attempt_id"])

    from ageval_sdk.agent import Agent
    from ageval_sdk.context import RunContext, RunParameterView, RunScope
    from ageval_sdk.terminal import RunTerminal

    artifact_dir = _box_dir("AGEVAL_ARTIFACTS")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    ctx = RunContext(
        params=RunParameterView(launch.get("params") or {}),
        scope=RunScope(
            attempt_id=attempt_id,
            trial_id=str(launch.get("trial_id") or ""),
            run_id=str(launch.get("run_id") or ""),
        ),
        workspace_root=_box_dir("AGEVAL_WORKSPACE"),
        artifact_dir=artifact_dir,
        dataset_root=dataset_root,
        agent=Agent(attempt_id=attempt_id),
    )
    try:
        entry = _load_entry(task_root, str(launch["entrypoint"]), dataset_root)
        outcome = entry(ctx)
        if asyncio.iscoroutine(outcome):
            outcome = await outcome
        if isinstance(outcome, RunTerminal):
            terminal = outcome.to_dict()
        elif outcome is None:
            terminal = RunTerminal.completed().to_dict()
        else:
            terminal = RunTerminal.failed("invalid_terminal").to_dict()
        frames.send(
            {
                "ok": True,
                "terminal": terminal,
                "published": {k: str(v) for k, v in (ctx.published or {}).items()},
                "attempt_id": attempt_id,
            }
        )
        return 0
    except Exception as exc:  # noqa: BLE001 — the envelope is the parent's only report
        frames.send(
            {
                "ok": False,
                **failure_envelope(exc),
                "attempt_id": attempt_id,
                "traceback": traceback.format_exc(limit=5),
            }
        )
        return 1
    finally:
        ctx.close()


def main() -> int:
    return asyncio.run(_run(_claim_stdout()))


if __name__ == "__main__":
    raise SystemExit(main())
