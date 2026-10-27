"""Execute a diagnosed terminal-action program inside the fresh box.

Core stores the new observations and the first divergence. The bound executor
dispatches each action. This module does not call a model and does not read
recorded stdout back as the result.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ageval.evidence.locators import default_runs_root
from ageval.evidence.redaction import redact_value
from ageval.evidence.replay_input import (
    COMPARATOR_ID,
    REPLAY_PROVENANCE_FORMAT,
    action_divergence,
)
from ageval.evidence.store import REPLAY_OBSERVATIONS_REL, TASK_ARTIFACTS_REL
from ageval.evidence.trajectory import TRAJECTORY_FILENAME

_SESSION = "replay"
_INVOKE = "replay"


async def execute_recorded_actions(ctx: Any) -> dict[str, object]:
    """Run the manifest in order. Stop at the first meaningful divergence."""
    manifest = ctx.replay_plan if isinstance(ctx.replay_plan, Mapping) else {}
    actions = manifest.get("actions")
    planned = (
        [item for item in actions if isinstance(item, Mapping)] if isinstance(actions, list) else []
    )
    executable = [item for item in planned if item.get("executable") is True]
    observations: list[dict[str, object]] = []
    divergence: dict[str, object] | None = None
    reproduced = False
    executed = 0
    try:
        placement = ctx.host.placement()
        dispatch = _dispatch(ctx)
        for action in executable:
            observed = await dispatch(ctx.host, action, placement)
            executed += 1
            exit_code = int(observed.get("exit_code") or 0)
            output = str(observed.get("output") or "")
            _record_observation(ctx, action, exit_code, output)
            row = {
                "ordinal": action.get("ordinal"),
                "tool_call_id": action.get("tool_call_id"),
                "exit_code": exit_code,
                "output": output,
                "raw_output": str(observed.get("raw_output") or output),
            }
            observations.append(row)
            found = action_divergence(action, exit_code, output)
            if found is not None:
                divergence = found
                break
            recorded_exit = action.get("recorded_exit_code")
            if (
                isinstance(recorded_exit, int)
                and not isinstance(recorded_exit, bool)
                and recorded_exit != 0
            ):
                reproduced = True
    except Exception as exc:  # noqa: BLE001 — the phase records the dispatch failure
        _store(ctx, observations, divergence, executed, len(executable), reproduced, error=True)
        return {
            "ok": False,
            "error": "terminal_replay_failed",
            "message": f"{type(exc).__name__}: {exc}",
        }
    _store(ctx, observations, divergence, executed, len(executable), reproduced, error=False)
    return {"ok": True, "replay_status": "diverged" if divergence else "matched"}


def note_artifact_divergence(ctx: Any) -> None:
    """Compare harvested declared artifacts after the action program stops."""
    provenance = ctx.replay_provenance if isinstance(ctx.replay_provenance, dict) else None
    if provenance is None or provenance.get("status") != "matched":
        return
    source = getattr(ctx, "replay_source_dir", None)
    if not isinstance(source, Path):
        return
    found = _artifact_divergence(ctx, source)
    if found is None:
        return
    provenance["status"] = "diverged"
    provenance["first_divergence"] = found
    provenance["reproduced_failure"] = False


def _dispatch(ctx: Any):
    from ageval.plugins.slots import EXECUTOR

    winner = ctx.bindings.winners.get(EXECUTOR)
    impl = getattr(winner, "impl", None)
    method = getattr(impl, "dispatch_terminal_action", None)
    if method is None:
        raise RuntimeError("terminal_replay_unsupported")
    return method


def _record_observation(
    ctx: Any, action: Mapping[str, object], exit_code: int, output: str
) -> None:
    log = ctx.activity
    if log is None:
        return
    call_id = str(action.get("tool_call_id") or f"bash_{action.get('ordinal')}")
    arguments = action.get("arguments")
    timeout = action.get("timeout_sec")
    log.append(
        request_id=f"tool_{_SESSION}_{call_id}",
        kind="tool_call",
        status="in_flight",
        payload={
            "session_id": _SESSION,
            "invoke_request_id": _INVOKE,
            "tool_call_id": call_id,
            "tool_name": "bash",
            "tool_kind": "execute",
            "arguments": dict(arguments) if isinstance(arguments, Mapping) else {},
            "replay_safe": False,
            "system_effect": False,
            "timeout_sec": float(timeout)
            if isinstance(timeout, int | float) and not isinstance(timeout, bool)
            else None,
            "deadline_utc": None,
        },
    )
    log.append(
        request_id=f"tool_{_SESSION}_{call_id}",
        kind="tool_call",
        status="completed",
        payload={
            "session_id": _SESSION,
            "invoke_request_id": _INVOKE,
            "tool_call_id": call_id,
            "outcome": "ok" if exit_code == 0 else "error",
            "exit_code": exit_code,
            "content": output,
            "stderr": None,
            "raw_output": None,
            "checkpoint_seq": None,
        },
    )


def _store(
    ctx: Any,
    observations: list[dict[str, object]],
    divergence: dict[str, object] | None,
    executed: int,
    planned: int,
    reproduced: bool,
    *,
    error: bool,
) -> None:
    root = ctx.evidence.root
    path = root / REPLAY_OBSERVATIONS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for row in observations:
        cleaned = redact_value(row)
        lines.append(json.dumps(cleaned, ensure_ascii=False, sort_keys=True))
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
    manifest = ctx.replay_plan if isinstance(ctx.replay_plan, Mapping) else {}
    identities = manifest.get("identities")
    source_ids = identities if isinstance(identities, Mapping) else {}
    status = "error" if error else "diverged" if divergence else "matched"
    payload: dict[str, object] = {
        "format": REPLAY_PROVENANCE_FORMAT,
        "parent_attempt_id": str(getattr(ctx, "replay_source_id", "") or ""),
        "source_locked_config_digest": str(source_ids.get("locked_config_digest") or ""),
        "child_locked_config_digest": str(getattr(ctx.lock, "digest", "") or ""),
        "tool_semantics": str(manifest.get("tool_semantics") or ""),
        "tool_semantics_version": str(manifest.get("tool_semantics_version") or ""),
        "status": status,
        "comparator": COMPARATOR_ID,
        "actions_executed": executed,
        "actions_planned": planned,
        "evaluated": False,
        "reproduced_failure": reproduced and divergence is None and not error,
    }
    if divergence is not None:
        payload["first_divergence"] = divergence
    ctx.replay_provenance = payload


def replay_display_rows(ctx: Any) -> list[dict[str, object]]:
    """Sealed trajectory rows for a replay that did not invoke a model.

    The page reads ``trajectory.jsonl``. Replay has no invocation archive, so
    the fold would otherwise seal an empty file. These rows are the task text
    from the source trajectory plus each action actually executed here, with
    the new observation. Model usage is not copied. The terminal records
    ``unavailable: not_reported`` so the seal accepts the file.
    """
    plan = ctx.replay_plan if isinstance(getattr(ctx, "replay_plan", None), Mapping) else None
    if plan is None:
        return []
    actions = plan.get("actions")
    planned = (
        [item for item in actions if isinstance(item, Mapping)] if isinstance(actions, list) else []
    )
    observations = _read_observations(getattr(getattr(ctx, "evidence", None), "root", None))
    by_id = {str(item.get("tool_call_id") or ""): item for item in observations}
    prompt, profile_id = _source_prompt(ctx)
    session_id = _SESSION
    rows: list[dict[str, object]] = []
    if prompt:
        rows.append(
            {
                "type": "turn",
                "role": "user",
                "content": prompt,
                "turn_index": 1,
                "session_id": session_id,
                "source": "ageval",
                "profile_id": profile_id,
            }
        )
    for action in planned:
        if action.get("executable") is not True:
            continue
        call_id = str(action.get("tool_call_id") or "")
        raw_args = action.get("arguments")
        arguments = raw_args if isinstance(raw_args, Mapping) else {}
        command = str(arguments.get("command") or "")
        observed = by_id.get(call_id, {})
        exit_code = observed.get("exit_code")
        status = "completed" if exit_code == 0 else "failed"
        raw = observed.get("raw_output")
        output = observed.get("output")
        content = raw if isinstance(raw, str) and raw else output if isinstance(output, str) else ""
        rows.append(
            {
                "type": "tool_call",
                "tool_call_id": call_id,
                "function_name": "bash",
                "title": "bash",
                "args": {"command": command},
                "status": status,
                "turn_index": 1,
                "session_id": session_id,
                "source": "miniswe",
                "profile_id": profile_id,
            }
        )
        rows.append(
            {
                "type": "observation",
                "tool_call_id": call_id,
                "status": status,
                "content": content,
                "raw_output": content,
                "turn_index": 1,
                "session_id": session_id,
                "source": "miniswe",
                "profile_id": profile_id,
            }
        )
    provenance = (
        ctx.replay_provenance
        if isinstance(getattr(ctx, "replay_provenance", None), Mapping)
        else {}
    )
    rows.append(
        {
            "type": "terminal",
            "ok": provenance.get("status") != "error",
            "error": None,
            "turn_index": 1,
            "session_id": session_id,
            "source": "ageval",
            "profile_id": profile_id,
            "usage": {"unavailable": "not_reported"},
            "metadata": {
                "executor_kind": "miniswe",
                "profile_id": profile_id,
                "replay": True,
                "parent_attempt_id": str(
                    provenance.get("parent_attempt_id")
                    or getattr(ctx, "replay_source_id", "")
                    or ""
                ),
                "replay_status": str(provenance.get("status") or ""),
            },
        }
    )
    return rows


def _read_observations(root: Path | None) -> list[dict[str, object]]:
    if root is None:
        return []
    path = root / REPLAY_OBSERVATIONS_REL
    if not path.is_file():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _source_prompt(ctx: Any) -> tuple[str, str]:
    parent = str(getattr(ctx, "replay_source_id", "") or "")
    dataset = getattr(ctx, "dataset_root", None)
    if not parent or not isinstance(dataset, Path) or parent in {".", ".."} or "/" in parent:
        return "", "solver"
    path = default_runs_root(dataset) / parent / TRAJECTORY_FILENAME
    if not path.is_file():
        return "", "solver"
    prompt = ""
    profile_id = "solver"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("type") == "turn" and row.get("role") == "user" and not prompt:
            prompt = str(row.get("content") or "")
        raw_profile = row.get("profile_id")
        if isinstance(raw_profile, str) and raw_profile.strip():
            profile_id = raw_profile.strip()
            if prompt:
                break
    return prompt, profile_id


def _artifact_divergence(ctx: Any, source: Path) -> dict[str, object] | None:
    refs = getattr(ctx.lock, "resolved_references", None) or {}
    declared = refs.get("artifacts") if isinstance(refs, Mapping) else None
    if not isinstance(declared, list):
        return None
    source_root = source / TASK_ARTIFACTS_REL
    child_root = ctx.evidence.path(TASK_ARTIFACTS_REL)
    for item in declared:
        if not isinstance(item, Mapping):
            continue
        aid = str(item.get("id") or "").strip()
        rel = str(item.get("path") or "").strip()
        if not aid or not rel:
            continue
        suffix = Path(rel).suffix or ".json"
        name = aid if str(item.get("kind") or "file") == "tree" else f"{aid}{suffix}"
        source_file = source_root / name
        child_file = child_root / name
        if not source_file.is_file():
            continue
        if not child_file.is_file() or source_file.read_bytes() != child_file.read_bytes():
            return {
                "ordinal": None,
                "tool_call_id": "",
                "field": "artifact",
                "artifact_id": aid,
                "recorded_exit_code": None,
                "observed_exit_code": None,
            }
    return None
