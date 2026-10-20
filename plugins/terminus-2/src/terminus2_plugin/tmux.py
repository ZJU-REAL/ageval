"""tmux session inside the attempt environment, driven only by ``host.exec``.

tmux is installed in the box when ``tmux -V`` fails. The evaluator host does
not need a tmux binary. A failed install raises ``EnvironmentFailure``.
"""

from __future__ import annotations

import asyncio
import shlex
import time
from typing import Any

from ageval.environments.protocol import EnvironmentFailure, ExecResult

_INSTALL = r"""
if tmux -V >/dev/null 2>&1; then
  exit 0
fi
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update && apt-get install -y --no-install-recommends tmux
elif command -v apk >/dev/null 2>&1; then
  apk add --no-cache tmux
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y tmux
elif command -v microdnf >/dev/null 2>&1; then
  microdnf install -y tmux
elif command -v yum >/dev/null 2>&1; then
  yum install -y tmux
else
  echo terminus2_tmux_no_package_manager >&2
  exit 3
fi
tmux -V
"""

_SPECIAL_KEYS = frozenset({"C-c", "C-d", "C-z", "Escape", "Enter"})


def run_exec(host: Any, command: list[str], **kwargs: Any) -> ExecResult:
    """Call ``host.exec`` from the executor thread."""
    coro = host.exec(command, **kwargs)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        result = asyncio.run(coro)
    else:
        code = "terminus2_exec_on_running_loop"
        raise EnvironmentFailure("environment_setup_failed", code)
    if not isinstance(result, ExecResult):
        code = "terminus2_exec_result_invalid"
        raise EnvironmentFailure("environment_setup_failed", code)
    return result


class TmuxSession:
    """One detached tmux session. Every call is ``bash -lc`` via the host."""

    def __init__(
        self,
        host: Any,
        *,
        session_name: str,
        cwd: str,
        user: str | None,
        pane_width: int,
        pane_height: int,
        cmd_timeout: float,
    ) -> None:
        self.host = host
        self.session_name = session_name
        self.cwd = cwd or "/attempt/workspace"
        self.user = user
        self.pane_width = pane_width
        self.pane_height = pane_height
        self.cmd_timeout = cmd_timeout
        self._started = False

    def ensure_tmux(self) -> None:
        """Install tmux in the box when it is missing. Fail closed."""
        probe = self._bash("tmux -V", user=self.user, timeout=30)
        if probe.exit_code == 0:
            return
        installed = self._bash(_INSTALL, user="0:0", timeout=min(self.cmd_timeout, 180) or 180)
        if installed.exit_code != 0:
            detail = (installed.stderr or installed.stdout or "").strip()
            code = "terminus2_tmux_unavailable"
            if detail:
                code = f"{code}:{detail[:400]}"
            raise EnvironmentFailure("environment_setup_failed", code)
        verify = self._bash("tmux -V", user=self.user, timeout=30)
        if verify.exit_code != 0:
            code = "terminus2_tmux_unavailable"
            raise EnvironmentFailure("environment_setup_failed", code)

    def start(self) -> None:
        self.ensure_tmux()
        name = shlex.quote(self.session_name)
        work = shlex.quote(self.cwd)
        width = int(self.pane_width)
        height = int(self.pane_height)
        # bash and its flags are separate tmux argv. One quoted string is a
        # missing binary, the session exits, and the server goes with it.
        script = (
            "export TERM=xterm-256color; "
            f"tmux new-session -d -s {name} -x {width} -y {height} -c {work} "
            "/bin/bash --noprofile --norc && "
            "tmux set-option -g default-shell /bin/bash && "
            "tmux set-option -g default-command /bin/bash && "
            "tmux set-option -g history-limit 100000"
        )
        opened = self._bash(script, user=self.user, timeout=self.cmd_timeout)
        if opened.exit_code != 0:
            detail = (opened.stderr or opened.stdout or "").strip()[:400]
            code = "terminus2_tmux_session_failed"
            if detail:
                code = f"{code}:{detail}"
            raise EnvironmentFailure("environment_setup_failed", code)
        self._started = True

    def send(self, keystrokes: str, duration: float) -> tuple[bool, str]:
        """Type ``keystrokes``. Return ``(completed, note)``.

        A trailing newline submits the line and waits up to ``duration``
        seconds for ``tmux wait done``. A timeout is a note, not an install
        failure. Special names such as ``C-c`` are tmux keys, not literals.
        """
        if not self._started:
            code = "terminus2_tmux_not_started"
            raise EnvironmentFailure("environment_setup_failed", code)
        wait = min(max(float(duration), 0.0), self.cmd_timeout)
        name = shlex.quote(self.session_name)
        stripped = keystrokes.strip()
        if stripped in _SPECIAL_KEYS and "\n" not in keystrokes and "\r" not in keystrokes:
            sent = self._bash(
                f"tmux send-keys -t {name} {stripped}",
                user=self.user,
                timeout=self.cmd_timeout,
            )
            self._require_send(sent)
            if wait:
                time.sleep(wait)
            return True, ""
        if not keystrokes:
            if wait:
                time.sleep(wait)
            return True, ""
        blocking = keystrokes.endswith(("\n", "\r"))
        body = keystrokes.rstrip("\r\n") if blocking else keystrokes
        if body:
            literal = self._bash(
                f"tmux send-keys -t {name} -l -- {shlex.quote(body)}",
                user=self.user,
                timeout=self.cmd_timeout,
            )
            self._require_send(literal)
        if not blocking:
            if wait:
                time.sleep(wait)
            return True, ""
        hook = self._bash(
            f"tmux send-keys -t {name} -l -- {shlex.quote('; tmux wait -S done')} "
            f"&& tmux send-keys -t {name} Enter",
            user=self.user,
            timeout=self.cmd_timeout,
        )
        self._require_send(hook)
        budget = max(wait, 0.1)
        waited = self._bash(
            f"timeout {budget:g}s tmux wait done",
            user=self.user,
            timeout=self.cmd_timeout + 5,
        )
        if waited.exit_code != 0:
            return False, f"tmux wait timed out after {budget:g}s"
        return True, ""

    def capture(self) -> str:
        if not self._started:
            code = "terminus2_tmux_not_started"
            raise EnvironmentFailure("environment_setup_failed", code)
        name = shlex.quote(self.session_name)
        shot = self._bash(
            f"tmux capture-pane -p -S - -t {name}",
            user=self.user,
            timeout=self.cmd_timeout,
        )
        if shot.exit_code != 0:
            detail = (shot.stderr or "").strip()[:400]
            code = "terminus2_tmux_capture_failed"
            if detail:
                code = f"{code}:{detail}"
            raise EnvironmentFailure("environment_setup_failed", code)
        return shot.stdout or ""

    def _require_send(self, result: ExecResult) -> None:
        if result.exit_code == 0:
            return
        detail = (result.stderr or result.stdout or "").strip()[:400]
        code = "terminus2_tmux_send_failed"
        if detail:
            code = f"{code}:{detail}"
        raise EnvironmentFailure("environment_setup_failed", code)

    def _bash(self, script: str, *, user: str | None, timeout: float) -> ExecResult:
        kwargs: dict[str, Any] = {"timeout_sec": float(timeout)}
        if self.cwd:
            kwargs["cwd"] = self.cwd
        if user:
            kwargs["user"] = user
        return run_exec(self.host, ["bash", "-lc", script], **kwargs)


__all__ = ["TmuxSession", "run_exec"]
