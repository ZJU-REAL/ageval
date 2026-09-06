"""ACP after_environment_ready probe: binary + stdio initialize; install only if missing."""

from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ageval.environments.protocol import EnvironmentFailure, ExecResult
from ageval.plugins.contrib.acp.hooks import (
    _PROBE_SOURCE,
    _ensure_entry_present,
    _install_line,
    _needed_commands,
    _pinned_packages,
    _probe_config,
)
from ageval.plugins.contrib.acp.registry import get_entry

ECHO = Path(__file__).resolve().parents[1] / "fixtures" / "acp" / "echo_agent.py"


@dataclass
class _Ctx:
    host: Any
    facts: list[tuple[str, dict[str, Any]]]

    def remaining_seconds(self) -> float:
        return 120.0

    def record_fact(self, name: str, detail: dict[str, Any] | None = None) -> None:
        self.facts.append((name, dict(detail or {})))


class _ScriptedHost:
    python_command = ("python3",)

    def __init__(self, probes: list[dict[str, Any]], *, install_code: int = 0) -> None:
        self._probes = list(probes)
        self.install_code = install_code
        self.commands: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []

    async def exec(self, command, **kwargs: Any) -> ExecResult:  # noqa: ANN001
        argv = [str(part) for part in command]
        self.commands.append(argv)
        self.kwargs.append(dict(kwargs))
        if len(argv) >= 3 and argv[1] == "-c":
            payload = self._probes.pop(0)
            return ExecResult(exit_code=0, stdout=json.dumps(payload), stderr="")
        return ExecResult(
            exit_code=self.install_code,
            stdout="",
            stderr="npm failed" if self.install_code else "",
        )


def _ok_probe(*, entry: str = "opencode") -> dict[str, Any]:
    desc = get_entry(entry)
    assert desc is not None
    pins = [
        {"package": pkg, "wanted": ver, "found": ver, "ok": True}
        for pkg, ver in _pinned_packages(desc)
    ]
    return {
        "ok": True,
        "missing": [],
        "versions": pins,
        "initialize": {"ok": True, "reason": "jsonrpc"},
    }


def _missing_probe() -> dict[str, Any]:
    return {
        "ok": False,
        "missing": ["opencode"],
        "versions": [],
        "initialize": {"ok": False, "reason": "skipped"},
    }


def _present_but_handshake_failed() -> dict[str, Any]:
    return {
        "ok": False,
        "missing": [],
        "versions": [],
        "initialize": {"ok": False, "reason": "no_jsonrpc_result"},
    }


@pytest.mark.asyncio
async def test_probe_hit_skips_install() -> None:
    desc = get_entry("opencode")
    assert desc is not None
    host = _ScriptedHost([_ok_probe()])
    ctx = _Ctx(host, [])
    await _ensure_entry_present(ctx, desc)
    assert len(host.commands) == 1
    assert host.commands[0][1] == "-c"
    assert ctx.facts[0][0] == "acp_runtime_probe"
    assert ctx.facts[0][1]["ok"] is True
    env = host.kwargs[0].get("env") or {}
    assert env.get("HOME")
    assert env.get("XDG_CONFIG_HOME", "").endswith("/.config")
    assert env.get("TERM") == "dumb"


@pytest.mark.asyncio
async def test_missing_binary_runs_entry_install_command_then_reprobes() -> None:
    desc = get_entry("opencode")
    assert desc is not None
    host = _ScriptedHost([_missing_probe(), _ok_probe()])
    ctx = _Ctx(host, [])
    await _ensure_entry_present(ctx, desc)
    assert host.commands[1] == ["bash", "-lc", _install_line(desc.install_command)]
    assert "opencode-ai@1.18.12" in desc.install_command
    assert "sudo -n" in host.commands[1][-1]
    names = [name for name, _ in ctx.facts]
    assert names == [
        "acp_runtime_probe",
        "acp_runtime_install",
        "acp_runtime_probe_after_install",
    ]
    assert ctx.facts[0][1]["ok"] is False
    assert ctx.facts[-1][1]["ok"] is True


@pytest.mark.asyncio
async def test_present_binary_does_not_npm_install_on_failed_probe() -> None:
    desc = get_entry("opencode")
    assert desc is not None
    host = _ScriptedHost([_present_but_handshake_failed()])
    ctx = _Ctx(host, [])
    with pytest.raises(EnvironmentFailure, match="not installing"):
        await _ensure_entry_present(ctx, desc)
    assert all(cmd[:2] != ["bash", "-lc"] for cmd in host.commands)


@pytest.mark.asyncio
async def test_install_failure_is_environment_failure() -> None:
    desc = get_entry("opencode")
    assert desc is not None
    host = _ScriptedHost([_missing_probe()], install_code=1)
    ctx = _Ctx(host, [])
    with pytest.raises(EnvironmentFailure) as ei:
        await _ensure_entry_present(ctx, desc)
    assert ei.value.kind == "acp_runtime_install_failed"


@pytest.mark.asyncio
async def test_still_wrong_after_install_fails_closed() -> None:
    desc = get_entry("opencode")
    assert desc is not None
    host = _ScriptedHost([_missing_probe(), _missing_probe()])
    ctx = _Ctx(host, [])
    with pytest.raises(EnvironmentFailure, match="still failing runtime probe"):
        await _ensure_entry_present(ctx, desc)


@pytest.mark.asyncio
async def test_no_install_command_fails_without_executing_install() -> None:
    real = get_entry("opencode")
    assert real is not None
    desc = SimpleNamespace(**{**real.as_dict(), "install_command": ""})
    host = _ScriptedHost([_missing_probe()])
    ctx = _Ctx(host, [])
    with pytest.raises(EnvironmentFailure, match="declares no install command"):
        await _ensure_entry_present(ctx, desc)  # type: ignore[arg-type]
    assert all(cmd[:2] != ["bash", "-lc"] for cmd in host.commands)


def test_opencode_pin_is_the_stdio_release() -> None:
    desc = get_entry("opencode")
    assert desc is not None
    assert _needed_commands(desc) == ["opencode"]
    assert _pinned_packages(desc) == [("opencode-ai", "1.18.12")]
    assert desc.acp_command == ("opencode", "acp")


def test_mode1_pins_engine_and_adapter() -> None:
    desc = get_entry("pi")
    assert desc is not None
    assert _needed_commands(desc) == ["pi", "pi-acp"]
    assert _pinned_packages(desc) == [
        ("pi-acp", "0.0.33"),
        ("@earendil-works/pi-coding-agent", "0.83.0"),
    ]


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run_probe_source(
    tmp_path: Path,
    *,
    npm_version: str,
    agent: str,
    handshake_timeout_sec: float | None = None,
) -> dict[str, Any]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _write_exec(
        bindir / "npm",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, sys",
                "pkg = sys.argv[-1]",
                f"ver = {json.dumps(npm_version)}",
                "print(json.dumps({'dependencies': {pkg: {'version': ver}}}))",
                "",
            ]
        ),
    )
    _write_exec(
        bindir / "opencode",
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(agent)} "$@"\n',
    )
    desc = get_entry("opencode")
    assert desc is not None
    config = _probe_config(desc)
    if handshake_timeout_sec is not None:
        config["handshake_timeout_sec"] = handshake_timeout_sec
    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE_SOURCE, json.dumps(config)],
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_probe_source_accepts_echo_stdio_agent(tmp_path: Path) -> None:
    result = _run_probe_source(tmp_path, npm_version="1.18.12", agent=str(ECHO))
    assert result["ok"] is True
    assert result["missing"] == []
    assert result["initialize"]["ok"] is True


def test_probe_source_ignores_npm_pin_when_binary_handshakes(tmp_path: Path) -> None:
    result = _run_probe_source(tmp_path, npm_version="1.1.35", agent=str(ECHO))
    assert result["ok"] is True
    assert result["missing"] == []
    assert result["versions"] == []
    assert result["initialize"]["ok"] is True


def test_probe_source_rejects_non_jsonrpc_stdio(tmp_path: Path) -> None:
    sleeper = tmp_path / "tcp_like.py"
    sleeper.write_text(
        "import sys, time\n"
        "print('INFO  acp server listening on 127.0.0.1', flush=True)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    result = _run_probe_source(
        tmp_path,
        npm_version="1.18.12",
        agent=str(sleeper),
        handshake_timeout_sec=1,
    )
    assert result["ok"] is False
    assert result["initialize"]["ok"] is False
    assert result["initialize"]["reason"] == "no_jsonrpc_result"
