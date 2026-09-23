"""Run the task's own ``run.py`` in a child process of the control plane.

The task drives its Agent session and publishes artifacts; it never touches the
box. That is why the worker is a child here rather than a process inside the
Attempt's box: the Agent is what runs in the box, reached over the Agent Service
socket, and the same arrangement works whether the box is this machine, a
container, or a sandbox on someone else's.

The channel is length-prefixed JSON over the child's own pipes: one launch
message in, one result envelope out.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import struct
import sys
import time
from pathlib import Path
from typing import Any

from ageval.attempt.ctx import AttemptCtx
from ageval.config.model import thaw
from ageval.environments.protocol import EVALUATION_PATH, WORKSPACE_PATH
from ageval.evidence.store import TASK_ARTIFACTS_REL
from ageval.runtime.offline import DEFAULT_OFFLINE_ENV, is_offline_agent

WORKER_MODULE = "ageval.runtime.task_worker"
EVAL_WORKER_MODULE = "ageval.runtime.eval_worker"
# Evaluate-phase clock. Distinct from the run worker's task_run_timeout envelope.
EVALUATE_TIMEOUT = "evaluate_timeout"
# stderr is diagnostics; keep the tail that fits in one evidence fact.
_STDERR_TAIL_BYTES = 4000


async def launch_task_worker(ctx: AttemptCtx) -> dict[str, Any]:
    """Run the task entrypoint and return its result envelope."""
    workspace = _worker_workspace(ctx)
    artifacts = ctx.evidence.path("task-artifacts")
    artifacts.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        WORKER_MODULE,
        cwd=str(workspace),
        env=_worker_env(ctx, workspace=workspace, artifacts=artifacts),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdin is not None
    process.stdin.write(_frame(_launch_message(ctx)))
    await process.stdin.drain()
    process.stdin.close()

    envelope = await _collect(process, timeout=ctx.remaining_seconds())
    if envelope.get("error") == "task_run_timeout":
        note = getattr(ctx, "note_limit_reached", None)
        if callable(note):
            note("wall_time_seconds")
    _record_artifacts(ctx, envelope)
    return envelope


async def launch_eval_worker(ctx: Any) -> dict[str, Any]:
    """Run ``evaluator.py`` in a parent child, same JSON-RPC socket as ``run.py``."""
    workspace = _eval_workspace(ctx)
    artifacts = ctx.evidence.path(TASK_ARTIFACTS_REL)
    artifacts.mkdir(parents=True, exist_ok=True)
    evaluation = _eval_gold_dir(ctx)
    workspace.mkdir(parents=True, exist_ok=True)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        EVAL_WORKER_MODULE,
        cwd=str(workspace),
        env=_eval_worker_env(ctx, workspace=workspace, artifacts=artifacts, evaluation=evaluation),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdin is not None
    process.stdin.write(_frame(_eval_launch_message(ctx)))
    await process.stdin.drain()
    return await _serve_eval_worker(process, ctx, timeout=ctx.remaining_seconds())


def _launch_message(ctx: AttemptCtx) -> dict[str, Any]:
    references = thaw(ctx.lock.resolved_references)
    return {
        "task_root": str(ctx.task_root),
        "dataset_root": str(ctx.dataset_root),
        "entrypoint": str(references["run_entrypoint"]),
        "params": thaw(ctx.lock.parameters),
        "attempt_id": ctx.attempt_id,
        "trial_id": ctx.trial_id,
        "run_id": ctx.run_id,
    }


def _worker_workspace(ctx: AttemptCtx) -> Path:
    """The directory ``run.py`` sees as the workspace.

    Seed is uploaded into the box. When this machine can see that directory
    (local, docker bind-mount), the worker must look there — a parallel empty
    evidence folder is not the workspace. Remote kinds without a shared
    filesystem keep a host-side copy of the seed so ``run.py`` can still read
    instruction files.
    """
    host_path = getattr(ctx.host, "host_path", None)
    if callable(host_path):
        mapped = host_path(WORKSPACE_PATH)
        return Path(str(mapped))
    workspace = ctx.evidence.path("task-workspace")
    seed = ctx.seed_dir
    if seed is not None and seed.is_dir():
        _copy_seed(seed, workspace)
    return workspace


def _copy_seed(source: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        target = dest / path.name
        if path.is_dir():
            shutil.copytree(path, target, dirs_exist_ok=True)
        else:
            shutil.copy2(path, target)


def _eval_workspace(ctx: Any) -> Path:
    """Scoring-host workspace when the parent can see the bind-mount."""
    from ageval.attempt.phases.evaluate import named_evaluate_environments

    if named_evaluate_environments(ctx):
        staged = ctx.evidence.path(TASK_ARTIFACTS_REL)
        from ageval.attempt.phases.evaluate import _workspace_tree_snapshots

        snapshots = _workspace_tree_snapshots(ctx, staged)
        if snapshots:
            return snapshots[0]
        staged.mkdir(parents=True, exist_ok=True)
        return staged
    host = getattr(ctx, "scoring_host", None) or ctx.host
    host_path = getattr(host, "host_path", None)
    if callable(host_path):
        mapped = Path(str(host_path(WORKSPACE_PATH)))
        mapped.mkdir(parents=True, exist_ok=True)
        return mapped
    return _worker_workspace(ctx)


def _eval_gold_dir(ctx: Any) -> Path:
    """Gold on the parent disk. The agent box never received this tree."""
    src = getattr(ctx, "evaluation_src", None)
    if src is not None and Path(src).is_dir():
        return Path(src)
    from ageval.attempt.phases.evaluate import named_evaluate_environments

    if named_evaluate_environments(ctx):
        empty = ctx.evidence.path("evaluation")
        empty.mkdir(parents=True, exist_ok=True)
        return empty
    host = getattr(ctx, "scoring_host", None) or ctx.host
    host_path = getattr(host, "host_path", None)
    if callable(host_path):
        mapped = Path(str(host_path(EVALUATION_PATH)))
        mapped.mkdir(parents=True, exist_ok=True)
        return mapped
    empty = ctx.evidence.path("evaluation")
    empty.mkdir(parents=True, exist_ok=True)
    return empty


def _eval_launch_message(ctx: Any) -> dict[str, Any]:
    references = thaw(ctx.lock.resolved_references)
    return {
        "task_root": str(ctx.task_root),
        "dataset_root": str(ctx.dataset_root),
        "entrypoint": str(references.get("evaluation_entrypoint") or "evaluator:evaluate"),
        "parameters": thaw(ctx.lock.parameters),
        "evaluation_inputs": references.get("evaluation_inputs") or [],
        "attempt_id": ctx.attempt_id,
        "trial_id": ctx.trial_id,
        "run_id": ctx.run_id,
    }


def _eval_worker_env(
    ctx: Any,
    *,
    workspace: Path,
    artifacts: Path,
    evaluation: Path,
) -> dict[str, str]:
    env = _worker_env(ctx, workspace=workspace, artifacts=artifacts)
    env["AGEVAL_EVALUATION"] = str(evaluation)
    return env


def _worker_env(ctx: AttemptCtx, *, workspace: Path, artifacts: Path) -> dict[str, str]:
    """Least privilege: where to write, whom to call, and nothing else."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": os.pathsep.join(p for p in sys.path if p and not p.endswith(".zip")),
        "PYTHONUNBUFFERED": "1",
        "LANG": os.environ.get("LANG", "C"),
        "AGEVAL_ATTEMPT_ID": ctx.attempt_id,
        "AGEVAL_WORKSPACE": str(workspace),
        "AGEVAL_ARTIFACTS": str(artifacts),
    }
    if ctx.agent_service is not None:
        env["AGEVAL_AGENT_SERVICE_SOCK"] = str(ctx.agent_service.socket_path)
    if is_offline_agent():
        env[DEFAULT_OFFLINE_ENV] = "1"
    return env


async def _read_frame(stream: asyncio.StreamReader) -> dict[str, Any]:
    header = await stream.readexactly(4)
    (size,) = struct.unpack("!I", header)
    if size > 8_000_000:
        raise ValueError("eval worker frame too large")
    body = await stream.readexactly(size)
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("eval worker frame is not an object")
    return parsed


def _remaining_seconds(ctx: Any) -> float | None:
    fn = getattr(ctx, "remaining_seconds", None)
    if not callable(fn):
        return None
    raw = fn()
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw)


def _clamp_timeout_sec(requested: float | None, remaining: float | None) -> float | None:
    if remaining is None:
        return requested
    if remaining <= 0:
        return 0.0
    if requested is None:
        return remaining
    return min(float(requested), remaining)


def _resolve_scoring_env(raw: object) -> dict[str, str]:
    """Only names the evaluator listed; values are parent locators, not literals.

    Accept ``${LOCATOR}`` or a bare locator name (task.yaml cannot use ``${}``).
    No vendor allowlist. Missing locators are omitted; the stage fails on its own.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("exec env must be a mapping of name -> locator")
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key)
        token = str(value).strip()
        if token.startswith("${") and token.endswith("}") and len(token) > 3:
            loc = token[2:-1]
        elif token.isidentifier() or (token.replace("_", "").isalnum() and token.upper() == token):
            loc = token
        else:
            raise ValueError(f"exec env {name} must be a locator, not a literal")
        found = os.environ.get(loc)
        if found:
            out[name] = found
    return out


async def _handle_eval_exec(ctx: Any, frame: dict[str, Any]) -> dict[str, Any]:
    from ageval.attempt.phases.evaluate import (
        UNKNOWN_EVALUATE_ENVIRONMENT,
        ensure_named_host,
        named_evaluate_environments,
    )

    req_id = frame.get("id")
    name = str(frame.get("environment") or "")
    argv = frame.get("argv")
    if not isinstance(argv, list) or not all(isinstance(part, str) for part in argv):
        return {"op": "exec_result", "id": req_id, "error": "invalid_exec_argv"}
    timeout = frame.get("timeout_sec")
    requested = float(timeout) if isinstance(timeout, int | float) else None
    remaining = _remaining_seconds(ctx)
    if remaining is not None and remaining <= 0:
        return {"op": "exec_result", "id": req_id, "error": EVALUATE_TIMEOUT}
    try:
        recipes = named_evaluate_environments(ctx)
        if recipes:
            if remaining is not None:
                host = await asyncio.wait_for(
                    ensure_named_host(ctx, name), timeout=max(0.1, remaining)
                )
            else:
                host = await ensure_named_host(ctx, name)
        else:
            # No named map: exec the singular scoring host (run box, or isolated one).
            host = getattr(ctx, "scoring_host", None)
            if host is None:
                return {
                    "op": "exec_result",
                    "id": req_id,
                    "error": UNKNOWN_EVALUATE_ENVIRONMENT,
                }
        leftover = _remaining_seconds(ctx)
        if leftover is not None and leftover <= 0:
            return {"op": "exec_result", "id": req_id, "error": EVALUATE_TIMEOUT}
        timeout_sec = _clamp_timeout_sec(requested, leftover if leftover is not None else remaining)
        env = _resolve_scoring_env(frame.get("env"))
        result = await host.exec(argv, timeout_sec=timeout_sec, env=env or None)
    except TimeoutError:
        return {"op": "exec_result", "id": req_id, "error": EVALUATE_TIMEOUT}
    except Exception as exc:  # noqa: BLE001 — worker gets one error, no retry
        message = str(exc)
        if message == UNKNOWN_EVALUATE_ENVIRONMENT or UNKNOWN_EVALUATE_ENVIRONMENT in message:
            error = UNKNOWN_EVALUATE_ENVIRONMENT
        else:
            error = message or type(exc).__name__
        return {"op": "exec_result", "id": req_id, "error": error}
    record = getattr(ctx, "record_fact", None)
    if callable(record):
        record("evaluate_exec", {"name": name, "exit_code": int(result.exit_code)})
    return {
        "op": "exec_result",
        "id": req_id,
        "exit_code": int(result.exit_code),
        "stdout": str(result.stdout or ""),
        "stderr": str(result.stderr or ""),
        "truncated": bool(getattr(result, "truncated", False)),
    }


def _attach_stderr(envelope: dict[str, Any], stderr: bytes) -> None:
    tail = stderr.decode("utf-8", errors="replace")[-_STDERR_TAIL_BYTES:]
    if not tail:
        return
    existing = str(envelope.get("stderr") or "")
    envelope["stderr"] = (existing + tail)[-_STDERR_TAIL_BYTES:] if existing else tail


async def _drain_stderr_tail(stream: asyncio.StreamReader) -> bytes:
    """Keep the last diagnostic bytes so a chatty evaluator cannot fill the pipe."""
    buf = b""
    while True:
        piece = await stream.read(65536)
        if not piece:
            return buf
        buf = (buf + piece)[-_STDERR_TAIL_BYTES:]


async def _serve_eval_worker(
    process: asyncio.subprocess.Process,
    ctx: Any,
    *,
    timeout: float | None,
) -> dict[str, Any]:
    """Launch stays open: worker may exec, then send the verdict envelope."""
    assert process.stdin is not None
    assert process.stdout is not None
    drain = (
        asyncio.create_task(_drain_stderr_tail(process.stderr))
        if process.stderr is not None
        else None
    )
    started = time.monotonic()
    try:
        while True:
            remaining = (
                None if timeout is None else max(0.1, timeout - (time.monotonic() - started))
            )
            try:
                frame = await asyncio.wait_for(_read_frame(process.stdout), timeout=remaining)
            except TimeoutError:
                process.kill()
                await process.wait()
                envelope: dict[str, Any] = {
                    "ok": False,
                    "error": EVALUATE_TIMEOUT,
                    "exit_code": process.returncode,
                }
                if drain is not None:
                    _attach_stderr(envelope, await drain)
                return envelope
            except asyncio.IncompleteReadError:
                await process.wait()
                envelope = {
                    "ok": False,
                    "error": "task_worker_no_result",
                    "exit_code": process.returncode,
                }
                if drain is not None:
                    _attach_stderr(envelope, await drain)
                return envelope
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                process.kill()
                await process.wait()
                envelope = {
                    "ok": False,
                    "error": "task_worker_unreadable_result",
                    "exit_code": process.returncode,
                }
                if drain is not None:
                    _attach_stderr(envelope, await drain)
                return envelope
            if frame.get("op") == "exec":
                reply = await _handle_eval_exec(ctx, frame)
                process.stdin.write(_frame(reply))
                await process.stdin.drain()
                continue
            process.stdin.close()
            await process.wait()
            frame["exit_code"] = process.returncode
            if drain is not None:
                _attach_stderr(frame, await drain)
            return frame
    except Exception:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        if drain is not None and not drain.done():
            drain.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await drain
        raise


async def _collect(
    process: asyncio.subprocess.Process,
    *,
    timeout: float | None,
) -> dict[str, Any]:
    """Read the envelope, keep the stderr tail, and reap the child."""
    assert process.stdout is not None
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return {"ok": False, "error": "task_run_timeout", "exit_code": process.returncode}

    envelope = _parse(stdout)
    envelope["exit_code"] = process.returncode
    tail = stderr.decode("utf-8", errors="replace")[-_STDERR_TAIL_BYTES:]
    if tail:
        envelope["stderr"] = tail
    return envelope


def _parse(stdout: bytes) -> dict[str, Any]:
    if len(stdout) < 4:
        return {"ok": False, "error": "task_worker_no_result"}
    (size,) = struct.unpack("!I", stdout[:4])
    body = stdout[4 : 4 + size]
    if len(body) < size:
        return {"ok": False, "error": "task_worker_truncated_result"}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "error": "task_worker_unreadable_result"}
    return parsed if isinstance(parsed, dict) else {"ok": False, "error": "task_worker_bad_result"}


def _record_artifacts(ctx: AttemptCtx, envelope: dict[str, Any]) -> None:
    """Keep artifact names in evidence; the bytes stay where they were written."""
    published = envelope.get("published")
    if not isinstance(published, dict):
        return
    names = {str(key): os.path.basename(str(value)) for key, value in published.items()}
    envelope["published"] = names
    ctx.record_fact("artifacts_published", {"ids": sorted(names)})


def _frame(obj: dict[str, Any]) -> bytes:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return struct.pack("!I", len(raw)) + raw
