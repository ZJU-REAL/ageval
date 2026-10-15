"""acp-oneshot talks to the box only through environment.exec."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tests.helpers.box import local_box

from ageval.environments.protocol import EnvironmentCapabilities, ExecResult
from ageval.model import ModelConfigError
from ageval.plugins.contrib.acp import build_acp_executor
from ageval.plugins.defaults import register_defaults
from ageval.plugins.errors import ExtensionMaterializeError, InjectUnsatisfiedError
from ageval.plugins.manifest import load_manifest
from ageval.plugins.protocol import BindingIntent, InjectRequirement
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.slots import ENVIRONMENT, EXECUTOR

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "acp-oneshot" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from acp_oneshot_plugin.container import AcpOneshotBoxExecutor  # noqa: E402
from acp_oneshot_plugin.factory import build_executor  # noqa: E402

from ageval.plugins.contrib.acp.hooks import store_entry_argv0  # noqa: E402
from ageval.plugins.contrib.acp.registry import clear_registry_cache  # noqa: E402

ECHO = ROOT / "tests" / "fixtures" / "acp" / "echo_agent.py"


class SpyHost:
    def __init__(self, attempt_root: Path) -> None:
        self._inner = local_box(attempt_root)
        self.commands: list[tuple[list[str], dict[str, str] | None]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def start(self, *, force_build: bool = False) -> None:
        await self._inner.start(force_build=force_build)

    async def stop(self, *, delete: bool) -> None:
        await self._inner.stop(delete=delete)

    async def exec(self, command, **kwargs: Any):  # type: ignore[no-untyped-def]
        env = kwargs.get("env")
        self.commands.append((list(command), dict(env) if env else None))
        return await self._inner.exec(command, **kwargs)


class EmptyStdoutHost(SpyHost):
    """Remote exec often returns exit 0 with empty stdout (e2b)."""

    async def exec(self, command, **kwargs: Any):  # type: ignore[no-untyped-def]
        result = await super().exec(command, **kwargs)
        return ExecResult(exit_code=result.exit_code, stdout="", stderr=result.stderr)


def _descriptor() -> Any:
    return SimpleNamespace(
        entry_id="pi",
        credential_env_names=("ZHIPU_API_KEY",),
        fixed_env={"NO_BROWSER": "1", "TERM": "dumb"},
        home_dirs=(".pi/agent",),
        acp_command=("pi-acp",),
        keyless_auth_paths=(),
    )


def _executor(host: Any, *, model: str = "entry-default") -> AcpOneshotBoxExecutor:
    return AcpOneshotBoxExecutor(
        host=host,
        placement=host.placement(),
        entry_id="pi",
        acp_command=[sys.executable, str(ECHO)],
        model=model,
        reasoning_effort=None,
        base_url=None,
        api_key_env="ZHIPU_API_KEY",
        profile_id="solver",
        credential_env_names=("ZHIPU_API_KEY",),
        fixed_env={"NO_BROWSER": "1"},
        descriptor=_descriptor(),
    )


@pytest.mark.asyncio
async def test_oneshot_worker_argv0_is_the_stored_absolute_path(tmp_path: Path) -> None:
    class _Capture(SpyHost):
        async def exec(self, command, **kwargs: Any):  # type: ignore[no-untyped-def]
            self.commands.append((list(command), None))
            return ExecResult(exit_code=0, stdout='{"ok": true, "text": "ok"}\n', stderr="")

    pinned = "/opt/pi-acp/bin/pi-acp"
    capture = _Capture(tmp_path)
    store_entry_argv0(capture, "pi", pinned)
    executor = _executor(capture)
    await executor._ainvoke("hi", timeout=5, collect_dir=None)
    request = json.loads(capture.commands[0][0][-1])
    assert request["acp_command"][0] == pinned
    assert request["acp_command"][1:] == [str(ECHO)]


def test_manifest_injects_environment_exec_only() -> None:
    manifest = load_manifest(ROOT / "plugins" / "acp-oneshot")
    assert manifest.plugin_id == "acp-oneshot"
    assert len(manifest.inject) == 1
    row = manifest.inject[0]
    assert row.service == "environment"
    assert set(row.capabilities) == {"exec"}
    assert "attach_stdio" not in row.capabilities


def test_lock_fails_when_environment_cannot_exec() -> None:
    class MuteHost:
        capabilities = EnvironmentCapabilities(attach_stdio=True)

    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(ENVIRONMENT, "mute", MuteHost, source="test", is_factory=True)
    registry.exclusive(EXECUTOR, "acp-oneshot", build_executor, source="test", is_factory=True)
    registry.declare_inject(
        "acp-oneshot",
        (InjectRequirement(service=ENVIRONMENT, capabilities=("exec",)),),
    )
    with pytest.raises(InjectUnsatisfiedError, match="exec"):
        resolve(
            BindingIntent(profile_id="solver", environment="mute", executor="acp-oneshot"),
            registry,
        )


def test_lock_succeeds_without_attach_stdio() -> None:
    class ExecOnlyHost:
        capabilities = EnvironmentCapabilities(exec=True)

    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(ENVIRONMENT, "exec-only", ExecOnlyHost, source="test", is_factory=True)
    registry.exclusive(EXECUTOR, "acp-oneshot", build_executor, source="test", is_factory=True)
    registry.declare_inject(
        "acp-oneshot",
        (InjectRequirement(service=ENVIRONMENT, capabilities=("exec",)),),
    )
    graph = resolve(
        BindingIntent(profile_id="solver", environment="exec-only", executor="acp-oneshot"),
        registry,
    )
    rows = graph.injects["acp-oneshot"]
    assert rows[0].service == "environment"
    assert set(rows[0].capabilities) == {"exec"}


def test_acp_still_requires_attach_stdio() -> None:
    class ExecOnlyHost:
        capabilities = EnvironmentCapabilities(exec=True)

    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(ENVIRONMENT, "exec-only", ExecOnlyHost, source="test", is_factory=True)
    registry.exclusive(EXECUTOR, "acp", build_acp_executor, source="test", is_factory=True)
    registry.declare_inject(
        "acp",
        (InjectRequirement(service=ENVIRONMENT, capabilities=("attach_stdio",)),),
    )
    with pytest.raises(InjectUnsatisfiedError, match="attach_stdio"):
        resolve(
            BindingIntent(
                profile_id="solver",
                environment="exec-only",
                executor="acp",
                options={"entry": "pi"},
            ),
            registry,
        )


def test_factory_requires_entry() -> None:
    host = local_box("/nowhere")
    with pytest.raises(ExtensionMaterializeError, match="acp_entry_required"):
        build_executor(host=host, placement=host.placement(), options={})


def test_factory_reads_nested_reasoning_effort() -> None:
    host = local_box("/nowhere")
    model = {"id": "zai-coding-cn/glm-5.2", "reasoning": {"effort": "xhigh"}}
    executor = build_executor(
        host=host,
        placement=host.placement(),
        options={"entry": "pi"},
        model=model,
    )
    assert executor.model == "zai-coding-cn/glm-5.2"
    assert executor.reasoning_effort == "xhigh"

    grok = build_executor(
        host=host,
        placement=host.placement(),
        options={"entry": "grok-build"},
        model={"id": "grok-4.5", "reasoning": {"effort": "low"}},
    )
    assert grok.reasoning_effort == "low"
    assert grok.acp_command[grok.acp_command.index("--reasoning-effort") + 1] == "low"
    assert grok.acp_command[grok.acp_command.index("--model") + 1] == "grok-4.5"


def test_factory_rejects_flat_reasoning_effort() -> None:
    host = local_box("/nowhere")
    with pytest.raises(ModelConfigError, match="model_flat_rejected:reasoning_effort"):
        build_executor(
            host=host,
            placement=host.placement(),
            options={"entry": "pi", "reasoning_effort": "high"},
            model={"id": "m"},
        )


def test_package_has_no_box_handle_or_entry_branch() -> None:
    root = ROOT / "plugins" / "acp-oneshot"
    offenders: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = str(path.relative_to(root))
        if "docker" + " exec" in text:
            offenders.append(f"{rel}: host docker CLI")
        if "container" + "_id" in text:
            offenders.append(f"{rel}: box handle field")
        if "if entry ==" in text or "if entry_id ==" in text:
            offenders.append(f"{rel}: entry branch")
        if "attach_stdio" in text and path.suffix == ".py":
            # README may mention the other family; code must not call it.
            offenders.append(f"{rel}: attach_stdio")
    assert offenders == []


@pytest.mark.asyncio
async def test_invoke_is_one_exec_against_echo_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-not-for-lock")
    host = SpyHost(tmp_path)
    await host.start()
    try:
        result = _executor(host).invoke("hello", timeout=15)
    finally:
        await host.stop(delete=True)

    assert result.ok is True
    assert result.text == '{"answer": 42}'
    assert result.structured == {"answer": 42}
    assert result.metadata is not None
    assert result.metadata.get("plugin") == "acp-oneshot"
    assert result.metadata.get("acp_entry_id") == "pi"
    assert len(host.commands) == 1
    command, env = host.commands[0]
    assert command[0] == sys.executable
    assert "-c" in command
    request = json.loads(command[-1])
    assert request["prompt"] == "hello"
    assert "sk-not-for-lock" not in json.dumps(request)
    assert "api_key" not in request
    assert env is not None
    assert env.get("ZHIPU_API_KEY") == "sk-not-for-lock"
    assert "AGEVAL_ACP_ONESHOT_WORKER" in env
    assert env.get("PATH") == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    assert "/Users/" not in (env.get("PATH") or "")
    assert request.get("result_path", "").endswith(".acp-oneshot-result.json")


@pytest.mark.asyncio
async def test_invoke_reads_result_file_when_stdout_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-not-for-lock")
    host = EmptyStdoutHost(tmp_path)
    await host.start()
    try:
        result = _executor(host).invoke("hello", timeout=15)
    finally:
        await host.stop(delete=True)
    assert result.ok is True
    assert result.error is None
    assert result.text == '{"answer": 42}'


def test_lock_cli_selects_oneshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ageval.plugins import bootstrap as boot
    from ageval.plugins.registry import reset_global_registry
    from ageval.plugins.store import install_from_path

    home = tmp_path / "ageval-home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()
    install_from_path(ROOT / "plugins" / "acp-oneshot")
    profiles = tmp_path / "profiles.yaml"
    profiles.write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                "environment: docker",
                "agent_profiles:",
                '  "*":',
                "    executor: acp-oneshot",
                "    model: {id: zai-coding-cn/glm-5.2}",
                "    api_key: ${ZHIPU_API_KEY}",
                "    options:",
                "      entry: pi",
                "    extensions:",
                "      - plugin: acp-oneshot",
                "      - plugin: docker",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["AGEVAL_HOME"] = str(home)
    env["ZHIPU_API_KEY"] = "sk-lock-must-not-see"
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
    assert solver["slots"]["executor"]["plugin"] == "acp-oneshot"
    inject = (solver.get("inject") or {}).get("acp-oneshot") or []
    caps = next(
        tuple(row.get("capabilities") or ())
        for row in inject
        if row.get("service") == "environment"
    )
    assert set(caps) == {"exec"}
    blob = json.dumps(data)
    assert "sk-lock-must-not-see" not in blob
    assert "ZHIPU_API_KEY" in blob or "api_key" in blob


def test_oneshot_resolves_a_home_file_entry() -> None:
    home = Path(os.environ["AGEVAL_HOME"])
    (home / "acp-entries.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "entry_id": "kimi",
                        "integration_mode": 2,
                        "execution_mode": "acp-stdio",
                        "engine_detect_commands": ["kimi"],
                        "acp_command": ["kimi", "acp"],
                        "acp_detect_commands": ["kimi"],
                        "acp_package": "@moonshot-ai/kimi-code",
                        "acp_version": "1.2.3",
                        "install_command": "npm install -g @moonshot-ai/kimi-code@1.2.3",
                        "credential_env_names": ["KIMI_API_KEY"],
                        "model_binding": "config-option",
                        "platforms": ["darwin", "linux"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    clear_registry_cache()
    built = build_executor(
        host=None,
        placement=None,
        options={"entry": "kimi"},
        model={"id": "entry-default"},
    )
    assert built.entry_id == "kimi"
    assert built.acp_command[:2] == ["kimi", "acp"]
