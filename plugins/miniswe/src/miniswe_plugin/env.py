"""Bash environment for mini-swe-agent, via the injected environment Protocol."""

from __future__ import annotations

import asyncio
from typing import Any

SUBMIT_MARK = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


def _run_host_exec(host: Any, command: list[str], **kwargs: Any) -> Any:
    """Run ``host.exec`` from the mini-swe-agent thread (no running loop there)."""
    coro = host.exec(command, **kwargs)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("miniswe env.execute cannot call host.exec on a running event loop")


def _check_submitted(output: dict[str, Any]) -> None:
    lines = str(output.get("output") or "").lstrip().splitlines(keepends=True)
    if not lines or lines[0].strip() != SUBMIT_MARK:
        return
    if int(output.get("returncode") or 0) != 0:
        return
    submission = "".join(lines[1:])
    try:
        from minisweagent.exceptions import Submitted
    except ImportError:
        return
    raise Submitted(
        {
            "role": "exit",
            "content": submission,
            "extra": {"exit_status": "Submitted", "submission": submission},
        }
    )


class ProtocolEnv:
    """Duck-types minisweagent.Environment; every bash action is ``host.exec``."""

    def __init__(self, *, host: Any, placement: Any, timeout: int = 30) -> None:
        self.host = host
        self.placement = placement
        self.timeout = timeout
        self.workdir = str(getattr(placement, "workdir", None) or "/attempt/workspace")
        self.user = getattr(placement, "user", None)
        self.config = type("Cfg", (), {"cwd": self.workdir, "timeout": timeout})()

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        command = str(action.get("command") or "")
        work = cwd or self.workdir
        kwargs: dict[str, Any] = {
            "cwd": work,
            "timeout_sec": float(timeout or self.timeout),
        }
        if self.user:
            kwargs["user"] = self.user
        request_id = getattr(self, "_exec_request_id", None)
        if isinstance(request_id, str) and request_id:
            kwargs["request_id"] = request_id
        try:
            result = _run_host_exec(self.host, ["bash", "-lc", command], **kwargs)
            output = f"{result.stdout or ''}{result.stderr or ''}"
            out: dict[str, Any] = {
                "output": output,
                "returncode": int(result.exit_code),
                "exception_info": "",
            }
        except Exception as exc:  # noqa: BLE001 — surface to the agent as a failed command
            out = {
                "output": "",
                "returncode": -1,
                "exception_info": f"{type(exc).__name__}:{exc}",
            }
        _check_submitted(out)
        return out

    def get_template_vars(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "system": "Linux",
            "release": "attempt",
            "version": "",
            "machine": "",
            **kwargs,
        }

    def serialize(self) -> dict[str, Any]:
        return {
            "info": {
                "config": {
                    "environment": {
                        "kind": getattr(self.host, "kind", None),
                        "workdir": self.workdir,
                    },
                    "environment_type": "miniswe_plugin.env.ProtocolEnv",
                }
            }
        }
