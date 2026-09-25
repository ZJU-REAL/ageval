"""Evaluator worker: run the task's ``evaluator.py`` in a parent subprocess.

Same shape as ``task_worker``: the control plane never imports the evaluator
module. The parent speaks length-prefixed JSON over pipes. ``Agent.session``
uses the host Agent Service socket, so ACP ``attach_stdio`` is the scoring
host's pipe — not a unix socket bind-mounted into the box.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ageval.runtime.task_worker import _claim_stdout, _extend_import_path, _Frames, failure_envelope

RESULT_NAME = "evaluation.json"


@dataclass(frozen=True)
class ScoringExecResult:
    """Protocol host.exec result, as seen by evaluator.py. Not PASS."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class ScoringFacade:
    """Ask the parent to exec on a named scoring host. No docker socket here."""

    def __init__(self, frames: _Frames) -> None:
        self._frames = frames
        self._n = 0

    async def exec(
        self,
        name: str,
        argv: list[str],
        timeout_sec: float | None = None,
        env: dict[str, str] | None = None,
    ) -> ScoringExecResult:
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError("unknown_evaluate_environment")
        if not isinstance(argv, list) or not all(isinstance(part, str) for part in argv):
            raise TypeError("scoring.exec argv must be a list of strings")
        self._n += 1
        payload: dict[str, Any] = {
            "op": "exec",
            "id": str(self._n),
            "environment": name.strip(),
            "argv": list(argv),
        }
        if timeout_sec is not None:
            payload["timeout_sec"] = timeout_sec
        if env:
            payload["env"] = {str(k): str(v) for k, v in env.items()}
        self._frames.send(payload)
        resp = self._frames.recv()
        error = resp.get("error")
        if error:
            raise RuntimeError(str(error))
        return ScoringExecResult(
            exit_code=int(resp.get("exit_code") or 0),
            stdout=str(resp.get("stdout") or ""),
            stderr=str(resp.get("stderr") or ""),
            truncated=bool(resp.get("truncated")),
        )


def _box_dir(env_name: str) -> Path:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        raise RuntimeError(f"evaluator worker missing {env_name}")
    return Path(raw)


def _load_entry(task_root: Path, entrypoint: str, dataset_root: Path | None) -> Any:
    module_name, _, func_name = entrypoint.partition(":")
    if not module_name or not func_name:
        raise ValueError(f"invalid entrypoint: {entrypoint}")
    path = task_root / f"{module_name}.py"
    if not path.is_file():
        raise FileNotFoundError(f"evaluator module missing: {path.name}")
    _extend_import_path(task_root, dataset_root)
    spec = importlib.util.spec_from_file_location("ageval_task_evaluator", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    func = getattr(module, func_name, None)
    if func is None:
        raise AttributeError(f"evaluator entrypoint missing: {entrypoint}")
    return func


def _published(artifacts_dir: Path) -> dict[str, str]:
    if not artifacts_dir.is_dir():
        return {}
    out: dict[str, str] = {}
    for item in sorted(artifacts_dir.iterdir()):
        if item.name == RESULT_NAME:
            continue
        if item.is_file():
            out[item.stem] = str(item)
        elif item.is_dir():
            out[item.name] = str(item)
    return out


def _maybe_agent(attempt_id: str) -> Any:
    sock = os.environ.get("AGEVAL_AGENT_SERVICE_SOCK", "").strip()
    if not sock or not attempt_id:
        return None
    try:
        from ageval_sdk import Agent
    except ImportError:
        return None
    return Agent(attempt_id=attempt_id)


def _run(frames: _Frames) -> int:
    launch = frames.recv()
    task_root = Path(launch["task_root"])
    dataset_raw = launch.get("dataset_root")
    dataset_root = Path(dataset_raw) if dataset_raw else None
    attempt_id = str(launch["attempt_id"])
    artifacts_dir = _box_dir("AGEVAL_ARTIFACTS")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = _box_dir("AGEVAL_WORKSPACE")
    evaluation_dir = _box_dir("AGEVAL_EVALUATION")
    try:
        func = _load_entry(task_root, str(launch["entrypoint"]), dataset_root)
        inputs: dict[str, Any] = {
            "artifacts": _published(artifacts_dir),
            "artifacts_dir": str(artifacts_dir),
            "workspace_dir": str(workspace_dir),
            "evaluation_dir": str(evaluation_dir),
            "inputs": launch.get("evaluation_inputs") or [],
            "parameters": launch.get("parameters") or {},
        }
        agent = _maybe_agent(attempt_id)
        if agent is not None:
            inputs["agent"] = agent
        inputs["scoring"] = ScoringFacade(frames)
        verdict = func(inputs)
        if asyncio.iscoroutine(verdict):
            verdict = asyncio.run(verdict)
        if not isinstance(verdict, dict):
            raise RuntimeError("evaluator verdict must be a JSON object")
        payload = json.dumps(verdict, sort_keys=True, ensure_ascii=False)
        (artifacts_dir / RESULT_NAME).write_text(payload, encoding="utf-8")
        frames.send({"ok": True, "verdict": verdict, "attempt_id": attempt_id})
        return 0
    except Exception as exc:  # noqa: BLE001 — envelope is the parent's only report
        frames.send(
            {
                "ok": False,
                **failure_envelope(exc),
                "attempt_id": attempt_id,
                "traceback": traceback.format_exc(limit=5),
            }
        )
        return 1


def main() -> int:
    return _run(_claim_stdout())


if __name__ == "__main__":
    raise SystemExit(main())
