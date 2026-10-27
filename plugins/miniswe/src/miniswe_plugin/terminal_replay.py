"""Re-execute recorded mini-swe bash actions through the environment.

Recovery replay returns a stored tool result so the model loop can continue.
This module does the other thing: it runs the command again and returns the
new observation. It does not call a model client.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ageval.evidence.replay_input import (
    TOOL_SEMANTICS_BASH,
    TOOL_SEMANTICS_VERSION,
    command_redacted,
)

_SUBMIT_MARK = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


def classify_actions(pairs: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Turn paired activity tool calls into an executable bash program."""
    actions: list[dict[str, object]] = []
    missing: list[str] = []
    for index, pair in enumerate(pairs, start=1):
        name = str(pair.get("tool_name") or "")
        kind = str(pair.get("tool_kind") or "")
        arguments = pair.get("arguments")
        args = dict(arguments) if isinstance(arguments, Mapping) else {}
        command = args.get("command")
        row_missing: list[str] = []
        if name != "bash" or kind != "execute":
            row_missing.append("unsupported_action")
        if not isinstance(command, str) or not command.strip():
            row_missing.append("command_missing")
        elif command_redacted(command):
            row_missing.append("command_redacted")
        if pair.get("completed") is not True:
            row_missing.append("action_incomplete")
        cwd = args.get("cwd")
        stored = {
            "command": command if isinstance(command, str) else "",
            "cwd": cwd if isinstance(cwd, str) and cwd.strip() else None,
        }
        actions.append(
            {
                "ordinal": index,
                "tool_call_id": str(pair.get("tool_call_id") or ""),
                "tool_name": name,
                "arguments": stored,
                "timeout_sec": pair.get("timeout_sec"),
                "recorded_exit_code": pair.get("recorded_exit_code"),
                "recorded_output": str(pair.get("recorded_output") or ""),
                "executable": not row_missing,
                "missing": row_missing,
            }
        )
        missing.extend(row_missing)
    return {
        "tool_semantics": TOOL_SEMANTICS_BASH,
        "tool_semantics_version": TOOL_SEMANTICS_VERSION,
        "actions": actions,
        "missing": list(dict.fromkeys(missing)),
    }


def comparable_output(stdout: str, stderr: str, exit_code: int) -> str:
    """Output shape stored on the original activity line.

    A submit marker is recorded as the submission body, matching the source
    activity writer. Other commands keep stdout and stderr concatenated.
    """
    output = f"{stdout}{stderr}"
    lines = output.lstrip().splitlines(keepends=True)
    if lines and lines[0].strip() == _SUBMIT_MARK and exit_code == 0:
        return "".join(lines[1:])
    return output


async def dispatch_bash(
    host: Any, action: Mapping[str, object], placement: Any
) -> dict[str, object]:
    """Run one recorded bash action on ``host``. The result is the new observation."""
    arguments = action.get("arguments")
    args = arguments if isinstance(arguments, Mapping) else {}
    command = str(args.get("command") or "")
    cwd = args.get("cwd")
    work = cwd.strip() if isinstance(cwd, str) and cwd.strip() else None
    if not work:
        work = str(getattr(placement, "workdir", "") or "") or None
    timeout = action.get("timeout_sec")
    kwargs: dict[str, object] = {}
    if work:
        kwargs["cwd"] = work
    if isinstance(timeout, int | float) and not isinstance(timeout, bool):
        kwargs["timeout_sec"] = float(timeout)
    user = getattr(placement, "user", None)
    if isinstance(user, str) and user:
        kwargs["user"] = user
    result = await host.exec(["bash", "-lc", command], **kwargs)
    exit_code = int(result.exit_code)
    stdout = str(result.stdout or "")
    stderr = str(result.stderr or "")
    return {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "output": comparable_output(stdout, stderr, exit_code),
        "raw_output": f"{stdout}{stderr}",
    }
