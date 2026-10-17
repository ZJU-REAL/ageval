"""dsh invoke goes through the environment Protocol, not a host SDK."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tests.helpers.box import local_box

from ageval.environments.protocol import EnvironmentCapabilities
from ageval.plugins.defaults import register_defaults
from ageval.plugins.errors import ExtensionMaterializeError, InjectUnsatisfiedError
from ageval.plugins.manifest import load_manifest
from ageval.plugins.protocol import BindingIntent, InjectRequirement
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.slots import ENVIRONMENT, EXECUTOR

ROOT = Path(__file__).resolve().parents[2]
_DSH_SRC = ROOT / "plugins" / "dsh" / "src"
if str(_DSH_SRC) not in sys.path:
    sys.path.insert(0, str(_DSH_SRC))

from dsh_plugin.factory import DshExecutorSPI, build_executor, resolve_max_tokens  # noqa: E402


class SpyHost:
    """Local box that records exec argv/env, then runs them for real."""

    def __init__(self, attempt_root: Path) -> None:
        self._inner = local_box(attempt_root)
        self.commands: list[tuple[list[str], dict[str, str] | None]] = []
        self.uploads: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def start(self, *, force_build: bool = False) -> None:
        await self._inner.start(force_build=force_build)

    async def stop(self, *, delete: bool) -> None:
        await self._inner.stop(delete=delete)

    async def upload(self, source: Path, dest: str) -> None:
        self.uploads.append(dest)
        await self._inner.upload(source, dest)

    async def exec(self, command, **kwargs: Any):  # type: ignore[no-untyped-def]
        env = kwargs.get("env")
        self.commands.append((list(command), dict(env) if env else None))
        return await self._inner.exec(command, **kwargs)


def test_manifest_injects_environment_exec_and_upload() -> None:
    manifest = load_manifest(ROOT / "plugins" / "dsh")
    assert len(manifest.inject) == 1
    row = manifest.inject[0]
    assert row.service == "environment"
    assert set(row.capabilities) == {"exec", "upload"}


def test_factory_returns_box_executor() -> None:
    host = local_box("/nowhere")
    executor = build_executor(
        host=host,
        placement=host.placement(),
        model="deepseek-v4-flash",
        api_key="litellm_api_key",
    )
    assert isinstance(executor, DshExecutorSPI)
    assert executor.kind == "dsh"


def test_lock_fails_when_environment_cannot_exec() -> None:
    class MuteHost:
        capabilities = EnvironmentCapabilities(upload=True)

    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(ENVIRONMENT, "mute", MuteHost, source="test", is_factory=True)
    registry.exclusive(EXECUTOR, "dsh", build_executor, source="test", is_factory=True)
    registry.declare_inject(
        "dsh",
        (InjectRequirement(service=ENVIRONMENT, capabilities=("exec", "upload")),),
    )
    with pytest.raises(InjectUnsatisfiedError, match="exec"):
        resolve(
            BindingIntent(profile_id="solver", environment="mute", executor="dsh"),
            registry,
        )


def test_lock_records_inject_when_box_can_exec() -> None:
    from ageval.plugins.contrib.local.host import LocalHost

    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(ENVIRONMENT, "local", LocalHost, source="test", is_factory=True)
    registry.exclusive(EXECUTOR, "dsh", build_executor, source="test", is_factory=True)
    registry.declare_inject(
        "dsh",
        (InjectRequirement(service=ENVIRONMENT, capabilities=("exec", "upload")),),
    )
    graph = resolve(
        BindingIntent(profile_id="solver", environment="local", executor="dsh"),
        registry,
    )
    rows = graph.injects["dsh"]
    assert rows[0].service == "environment"
    assert set(rows[0].capabilities) == {"exec", "upload"}


@pytest.mark.asyncio
async def test_invoke_runs_worker_through_local_exec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGEVAL_OFFLINE_AGENT", "1")
    monkeypatch.setenv("litellm_api_key", "sk-not-for-argv")
    monkeypatch.setenv("litellm_base_url", "https://example.invalid/v1")
    host = SpyHost(tmp_path)
    await host.start()
    try:
        executor = build_executor(
            host=host,
            placement=host.placement(),
            model="deepseek-v4-flash",
            api_key="litellm_api_key",
            base_url="https://example.invalid/v1",
        )
        result = executor.invoke("count the rows", timeout=30)
    finally:
        await host.stop(delete=True)

    assert result.ok is False
    assert result.error == "offline_forced"
    assert result.metadata is not None
    assert result.metadata.get("execution_location") == "attempt-container"
    assert result.metadata.get("plugin") == "dsh"
    assert host.uploads, "worker files must be uploaded into the box"
    assert host.commands, "invoke must call host.exec"
    command, env = next(
        (cmd, env) for cmd, env in host.commands if cmd and str(cmd[-1]).lstrip().startswith("{")
    )
    assert command[0] == sys.executable
    request = json.loads(command[-1])
    assert "max_tokens" not in request
    assert "sk-not-for-argv" not in json.dumps(request)
    assert "api_key" not in request
    assert env is not None
    assert env.get("DEEPSEEK_API_KEY") == "sk-not-for-argv"
    assert env.get("DEEPSEEK_BASE_URL") == "https://example.invalid/v1"
    factory_src = (ROOT / "plugins" / "dsh" / "src" / "dsh_plugin" / "factory.py").read_text(
        encoding="utf-8"
    )
    container_src = (ROOT / "plugins" / "dsh" / "src" / "dsh_plugin" / "container.py").read_text(
        encoding="utf-8"
    )
    assert "import deepseek_harness" not in factory_src
    assert "from deepseek_harness" not in factory_src
    assert "import deepseek_harness" not in container_src
    assert "from deepseek_harness" not in container_src
    worker_src = (ROOT / "plugins" / "dsh" / "worker" / "ageval_executor_dsh.py").read_text(
        encoding="utf-8"
    )
    assert "max_tokens=8192" not in worker_src


def test_resolve_max_tokens_omit_and_positive() -> None:
    assert resolve_max_tokens(None) is None
    assert resolve_max_tokens("") is None
    assert resolve_max_tokens("  ") is None
    assert resolve_max_tokens(8192) == 8192


@pytest.mark.parametrize("raw", [0, -1, True, False, 12.5, "8192", "x"])
def test_resolve_max_tokens_rejects_invalid(raw: object) -> None:
    with pytest.raises(ExtensionMaterializeError, match="dsh_max_tokens_invalid"):
        resolve_max_tokens(raw)


@pytest.mark.asyncio
async def test_invoke_forwards_options_max_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGEVAL_OFFLINE_AGENT", "1")
    monkeypatch.setenv("litellm_api_key", "sk-not-for-argv")
    host = SpyHost(tmp_path)
    await host.start()
    try:
        executor = build_executor(
            host=host,
            placement=host.placement(),
            model="deepseek-v4-flash",
            api_key="litellm_api_key",
            options={"max_tokens": 8192},
        )
        executor.invoke("count the rows", timeout=30)
    finally:
        await host.stop(delete=True)

    command, _env = next(
        (cmd, env) for cmd, env in host.commands if cmd and str(cmd[-1]).lstrip().startswith("{")
    )
    request = json.loads(command[-1])
    assert request["max_tokens"] == 8192


class _PiplessHost:
    """Debian-style box: python3 exists, pip and ensurepip do not."""

    python_command = ("python3",)

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.has_pip = False
        self.installed = False

    async def exec(self, command, **kwargs: Any):  # type: ignore[no-untyped-def]
        del kwargs
        from ageval.environments.protocol import ExecResult

        argv = [str(part) for part in command]
        self.calls.append(argv)
        joined = " ".join(argv)
        if "-c" in argv and "import missingmod" in joined:
            if self.installed:
                return ExecResult(exit_code=0, stdout="", stderr="")
            return ExecResult(exit_code=1, stdout="", stderr="ModuleNotFoundError")
        if "-c" in argv and "get-pip.py" in joined:
            return ExecResult(exit_code=0, stdout="fetched", stderr="")
        if "/tmp/get-pip.py" in argv:
            self.has_pip = True
            return ExecResult(exit_code=0, stdout="", stderr="")
        if argv[1:3] == ["-m", "pip"] and "--version" in argv:
            if self.has_pip:
                return ExecResult(exit_code=0, stdout="pip 24.0", stderr="")
            return ExecResult(exit_code=1, stdout="", stderr="No module named pip")
        if argv[1:3] == ["-m", "ensurepip"]:
            return ExecResult(exit_code=1, stdout="", stderr="No module named ensurepip")
        if argv[1:3] == ["-m", "pip"] and "install" in argv:
            if self.has_pip and "--break-system-packages" in argv:
                self.installed = True
                return ExecResult(exit_code=0, stdout="", stderr="")
            return ExecResult(
                exit_code=1,
                stdout="",
                stderr="No module named pip" if not self.has_pip else "externally-managed",
            )
        return ExecResult(exit_code=1, stdout="", stderr="unexpected")


@pytest.mark.asyncio
async def test_ensure_import_bootstraps_get_pip_when_image_has_none() -> None:
    from dsh_plugin.container import _ensure_import

    host = _PiplessHost()
    placement = SimpleNamespace(workdir="/attempt/workspace")
    await _ensure_import(host, placement, module="missingmod", spec="missingmod==1")
    assert host.installed is True
    assert any("/tmp/get-pip.py" in call for call in host.calls)
    assert any("--break-system-packages" in call for call in host.calls)


class _Py311Host:
    """Box python is 3.11; the wheel needs 3.12."""

    python_command = ("python3",)

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.installed = False

    async def exec(self, command, **kwargs: Any):  # type: ignore[no-untyped-def]
        del kwargs
        from ageval.environments.protocol import ExecResult

        argv = [str(part) for part in command]
        self.calls.append(argv)
        joined = " ".join(argv)
        if "-c" in argv and "import missingmod" in joined:
            if self.installed:
                return ExecResult(exit_code=0, stdout="", stderr="")
            return ExecResult(exit_code=1, stdout="", stderr="ModuleNotFoundError")
        if argv[:2] == ["sh", "-c"]:
            self.python_command = ("/tmp/ageval-py/bin/python",)
            return ExecResult(exit_code=0, stdout="AGEVAL_VENV=/tmp/ageval-py\n", stderr="")
        if "-m" in argv and "pip" in argv and "--version" in argv:
            return ExecResult(exit_code=0, stdout="pip 24.0", stderr="")
        if "-m" in argv and "pip" in argv and "install" in argv:
            if "ageval-py" in argv[0]:
                self.installed = True
                return ExecResult(exit_code=0, stdout="", stderr="")
            return ExecResult(
                exit_code=1,
                stdout="",
                stderr=(
                    "ERROR: Could not find a version that satisfies the requirement "
                    "missingmod==1 (from versions: none)\n"
                    "0.0.7 Requires-Python >=3.12,<3.14"
                ),
            )
        return ExecResult(exit_code=1, stdout="", stderr="unexpected")


@pytest.mark.asyncio
async def test_ensure_import_bootstraps_cpython_when_wheel_needs_312() -> None:
    from dsh_plugin.container import _ensure_import

    host = _Py311Host()
    placement = SimpleNamespace(workdir="/attempt/workspace")
    await _ensure_import(host, placement, module="missingmod", spec="missingmod==1")
    assert host.installed is True
    assert host.python_command == ("/tmp/ageval-py/bin/python",)
    assert any(call[:2] == ["sh", "-c"] for call in host.calls)
