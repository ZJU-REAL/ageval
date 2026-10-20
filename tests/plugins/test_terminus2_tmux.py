"""tmux setup and keystroke exchange through a fake environment.exec."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ageval.environments.protocol import EnvironmentFailure, ExecResult

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "terminus-2" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from terminus2_plugin.tmux import TmuxSession  # noqa: E402


class FakeHost:
    def __init__(self, handler) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self._handler = handler

    async def exec(self, command, **kwargs):
        argv = [str(part) for part in command]
        self.calls.append((argv, dict(kwargs)))
        script = argv[-1] if argv else ""
        return self._handler(script, kwargs)


def _scripts(host: FakeHost) -> list[str]:
    return [call[0][-1] for call in host.calls]


def test_present_tmux_skips_install() -> None:
    def handler(script: str, kwargs: dict) -> ExecResult:
        del kwargs
        if script.strip() == "tmux -V":
            return ExecResult(exit_code=0, stdout="tmux 3.3a\n")
        if "new-session" in script:
            return ExecResult(exit_code=0)
        return ExecResult(exit_code=0, stdout="")

    host = FakeHost(handler)
    session = TmuxSession(
        host,
        session_name="t2test",
        cwd="/attempt/workspace",
        user="10001:10001",
        pane_width=80,
        pane_height=24,
        cmd_timeout=30,
    )
    session.start()
    scripts = _scripts(host)
    assert all("apt-get" not in script for script in scripts)
    opened = next(script for script in scripts if "new-session" in script)
    assert "-c /attempt/workspace" in opened
    assert host.calls[0][1]["user"] == "10001:10001"


def test_missing_tmux_installs_then_opens_session() -> None:
    state = {"probes": 0}

    def handler(script: str, kwargs: dict) -> ExecResult:
        if script.strip() == "tmux -V":
            state["probes"] += 1
            if state["probes"] == 1:
                return ExecResult(exit_code=127, stderr="tmux: not found")
            return ExecResult(exit_code=0, stdout="tmux 3.3a\n")
        if "apt-get install" in script:
            assert kwargs.get("user") == "0:0"
            return ExecResult(exit_code=0, stdout="installed\n")
        if "new-session" in script:
            return ExecResult(exit_code=0)
        return ExecResult(exit_code=0)

    host = FakeHost(handler)
    session = TmuxSession(
        host,
        session_name="t2test",
        cwd="/attempt/workspace",
        user="10001:10001",
        pane_width=80,
        pane_height=24,
        cmd_timeout=30,
    )
    session.start()
    scripts = _scripts(host)
    assert any("apt-get install" in script for script in scripts)
    assert scripts[-1].find("new-session") >= 0


def test_install_failure_is_a_typed_environment_error() -> None:
    def handler(script: str, kwargs: dict) -> ExecResult:
        del kwargs
        if script.strip() == "tmux -V":
            return ExecResult(exit_code=127, stderr="missing")
        return ExecResult(exit_code=3, stderr="terminus2_tmux_no_package_manager")

    host = FakeHost(handler)
    session = TmuxSession(
        host,
        session_name="t2test",
        cwd="/attempt/workspace",
        user=None,
        pane_width=80,
        pane_height=24,
        cmd_timeout=30,
    )
    with pytest.raises(EnvironmentFailure) as raised:
        session.start()
    assert raised.value.kind == "environment_setup_failed"
    assert "terminus2_tmux_unavailable" in raised.value.message
    assert all("new-session" not in script for script in _scripts(host))


def test_send_then_capture_exchanges_keystrokes() -> None:
    panes = {"text": "$ "}

    def handler(script: str, kwargs: dict) -> ExecResult:
        del kwargs
        if script.strip() == "tmux -V" or "new-session" in script:
            return ExecResult(exit_code=0, stdout="tmux 3.3a\n")
        if "send-keys" in script and "printf" in script:
            panes["text"] += "printf 'hello' > hello.txt\n"
            return ExecResult(exit_code=0)
        if "tmux wait -S done" in script:
            panes["text"] += "hello.txt written\n$ "
            return ExecResult(exit_code=0)
        if script.startswith("timeout") and "tmux wait done" in script:
            return ExecResult(exit_code=0)
        if "capture-pane" in script:
            return ExecResult(exit_code=0, stdout=panes["text"])
        return ExecResult(exit_code=0)

    host = FakeHost(handler)
    session = TmuxSession(
        host,
        session_name="t2test",
        cwd="/attempt/workspace",
        user="10001:10001",
        pane_width=80,
        pane_height=24,
        cmd_timeout=30,
    )
    session.start()
    completed, note = session.send("printf 'hello' > hello.txt\n", 0.5)
    assert completed is True
    assert note == ""
    screen = session.capture()
    assert "hello.txt written" in screen
    scripts = _scripts(host)
    send_at = next(
        i for i, script in enumerate(scripts) if "send-keys" in script and "printf" in script
    )
    capture_at = next(i for i, script in enumerate(scripts) if "capture-pane" in script)
    assert send_at < capture_at
