"""Parse a scripted reply, then drive tmux through environment.exec. No live model."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from ageval.environments.protocol import (
    WORKSPACE_PATH,
    EnvironmentCapabilities,
    ExecResult,
    Placement,
)
from ageval.model import ModelSpec
from ageval.plugins.defaults import register_defaults
from ageval.plugins.errors import InjectUnsatisfiedError
from ageval.plugins.protocol import BindingIntent, InjectRequirement
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.slots import ENVIRONMENT, EXECUTOR

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "terminus-2" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from terminus2_plugin.episode import run_episode  # noqa: E402
from terminus2_plugin.factory import Terminus2ExecutorSPI, build_executor  # noqa: E402
from terminus2_plugin.model_client import ModelReply, complete  # noqa: E402
from terminus2_plugin.tmux import TmuxSession  # noqa: E402
from terminus2_plugin.trajectory import SCHEMA  # noqa: E402

_REPLY = json.dumps(
    {
        "analysis": "pane is empty",
        "plan": "write hello.txt",
        "commands": [{"keystrokes": "printf 'hello\\n' > hello.txt\n", "duration": 0.1}],
        "task_complete": True,
    }
)


class _Reply:
    def __init__(self, text: str) -> None:
        self.text = text
        self.usage = {"prompt_tokens": 4, "completion_tokens": 6}


class FakeHost:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def exec(self, command, **kwargs):
        del kwargs
        script = str(command[-1]) if command else ""
        self.calls.append(script)
        if "capture-pane" in script:
            return ExecResult(exit_code=0, stdout="$ \n")
        if script.strip() == "tmux -V":
            return ExecResult(exit_code=0, stdout="tmux 3.3a\n")
        return ExecResult(exit_code=0)


def _session(host: FakeHost) -> TmuxSession:
    return TmuxSession(
        host,
        session_name="t2ep",
        cwd=WORKSPACE_PATH,
        user="10001:10001",
        pane_width=80,
        pane_height=24,
        cmd_timeout=30,
    )


def test_episode_parses_then_sends_keystrokes_before_capture() -> None:
    host = FakeHost()
    seen: list[str] = []

    def model(messages):
        seen.append(messages[-1]["content"])
        return _Reply(_REPLY)

    result = run_episode(
        instruction="write hello.txt",
        session=_session(host),
        model=model,
        parser="json",
        step_limit=4,
        max_format_errors=2,
        timeout=30,
        session_id="s1",
    )
    assert result.ok is True
    assert result.keys_sent is True
    assert any("write hello.txt" in text for text in seen)
    send_at = next(i for i, script in enumerate(host.calls) if "printf" in script)
    capture_after = next(
        i for i, script in enumerate(host.calls) if i > send_at and "capture-pane" in script
    )
    assert send_at < capture_after
    assert any("new-session" in script for script in host.calls[:send_at])
    tools = [event for event in result.events if event.get("kind") == "tool"]
    assert tools[0]["schema"] == SCHEMA
    assert tools[0]["phase"] == "start"
    assert tools[1]["phase"] == "update"
    assert tools[1]["status"] == "completed"
    assert "printf" in tools[0]["args"]["keystrokes"]


def test_format_errors_do_not_touch_tmux_keys() -> None:
    host = FakeHost()

    def model(messages):
        del messages
        return _Reply("not json")

    result = run_episode(
        instruction="write hello.txt",
        session=_session(host),
        model=model,
        parser="json",
        step_limit=4,
        max_format_errors=2,
        timeout=30,
        session_id="s1",
    )
    assert result.ok is False
    assert result.error is not None and result.error.startswith("terminus2_format:")
    assert result.keys_sent is False
    assert all("send-keys" not in script for script in host.calls)


def test_invoke_records_events_and_is_not_repeatable_after_keys(monkeypatch) -> None:
    host = FakeHost()
    host.kind = "docker"  # type: ignore[attr-defined]

    def fake_complete(messages, **kwargs):
        del messages, kwargs
        return ModelReply(text=_REPLY, usage={"prompt_tokens": 4, "completion_tokens": 6})

    monkeypatch.setattr("terminus2_plugin.factory.complete", fake_complete)
    spi = Terminus2ExecutorSPI(
        host=host,
        placement=Placement(target_id="box", user="10001:10001", workdir=WORKSPACE_PATH),
        options={"parser": "json", "step_limit": 2, "cmd_timeout": 30},
        model={"id": "mock", "api": "chat"},
        base_url="http://127.0.0.1:9/v1",
        api_key="OPENAI_API_KEY",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    result = spi.invoke("write hello.txt", timeout=30)
    assert result.ok is True
    assert result.repeatable is False
    assert result.events[0]["source"] == "terminus-2"
    assert result.usage.prompt_tokens == 4  # type: ignore[union-attr]


def test_http_401_is_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(request, timeout=0):
        del request, timeout
        raise urllib.error.HTTPError(
            "http://127.0.0.1/v1/chat/completions",
            401,
            "no",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b"{}"),
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    spec = ModelSpec(id="mock", api="chat", reasoning_effort=None, timeout=5, watchdog=5, extra={})
    with pytest.raises(Exception, match="terminus2_http_401") as raised:
        complete(
            [{"role": "user", "content": "hi"}],
            spec=spec,
            api_key="k",
            base_url="http://127.0.0.1:9/v1",
            invoke_timeout=5,
        )
    assert type(raised.value).__name__ == "ModelConfigError"


def test_lock_fails_when_environment_cannot_exec() -> None:
    class MuteHost:
        capabilities = EnvironmentCapabilities(upload=True)

    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(ENVIRONMENT, "mute", MuteHost, source="test", is_factory=True)
    registry.exclusive(EXECUTOR, "terminus-2", build_executor, source="test", is_factory=True)
    registry.declare_inject(
        "terminus-2",
        (InjectRequirement(service=ENVIRONMENT, capabilities=("exec",)),),
    )
    with pytest.raises(InjectUnsatisfiedError, match="exec"):
        resolve(
            BindingIntent(profile_id="solver", environment="mute", executor="terminus-2"),
            registry,
        )


def test_lock_cli_records_exec_inject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ageval.plugins import bootstrap as boot
    from ageval.plugins.registry import reset_global_registry
    from ageval.plugins.store import install_from_path

    home = tmp_path / "ageval-home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()
    install_from_path(ROOT / "plugins" / "terminus-2")
    profiles = tmp_path / "profiles.terminus2.yaml"
    profiles.write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                "environment: docker",
                "agent_profiles:",
                "  solver:",
                "    executor: terminus-2",
                "    extensions:",
                "      - plugin: terminus-2",
                "        options:",
                "          parser: json",
                "          step_limit: 4",
                "      - plugin: docker",
                "    model: {id: openai/mock, api: chat}",
                "    api_key: ${OPENAI_API_KEY}",
                "    base_url: ${OPENAI_BASE_URL}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["AGEVAL_HOME"] = str(home)
    env["OPENAI_API_KEY"] = "sk-lock-must-not-see"
    env["OPENAI_BASE_URL"] = "https://example.invalid/v1"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ageval.cli.main",
            "lock",
            str(ROOT / "examples/datasets/minimal-demo"),
            "--task",
            "terminal-jsonl-agg",
            "--profiles",
            str(profiles),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    data = json.loads(proc.stdout)
    solver = data["extension_bindings"]["solver"]
    assert solver["slots"]["executor"]["plugin"] == "terminus-2"
    inject = (solver.get("inject") or {}).get("terminus-2") or []
    caps = next(
        tuple(row.get("capabilities") or ())
        for row in inject
        if row.get("service") == "environment"
    )
    assert set(caps) == {"exec"}
    assert "sk-lock-must-not-see" not in json.dumps(data)
