"""nooa invoke goes through the environment Protocol, not a host SDK."""

from __future__ import annotations

import json
import sys
from pathlib import Path
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
_NOOA_SRC = ROOT / "plugins" / "nooa" / "src"
if str(_NOOA_SRC) not in sys.path:
    sys.path.insert(0, str(_NOOA_SRC))

from nooa_plugin.factory import NooaExecutorSPI, build_executor  # noqa: E402

_FIXED_AGENT = """\
from typing import Any

class FixedAnswerAgent:
    def run(self, prompt: str, workdir: str | None = None) -> dict[str, Any]:
        del prompt, workdir
        return {"ok": True, "text": "42", "structured": {"answer": 42}}
"""


class SpyHost:
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
    manifest = load_manifest(ROOT / "plugins" / "nooa")
    assert len(manifest.inject) == 1
    row = manifest.inject[0]
    assert row.service == "environment"
    assert set(row.capabilities) == {"exec", "upload"}


def test_factory_requires_agent_option() -> None:
    host = local_box("/nowhere")
    with pytest.raises(ExtensionMaterializeError, match="nooa_options_agent_required"):
        build_executor(host=host, placement=host.placement(), options={})


def test_lock_rejects_unknown_model_extra(tmp_path: Path) -> None:
    from tests.helpers.lock import lock_with_profiles

    from ageval.model.errors import ModelConfigError
    from ageval.plugins.bootstrap import ensure_bootstrapped

    reg = ensure_bootstrapped()
    saved = reg._injects.get("nooa")
    reg.exclusive(
        EXECUTOR, "nooa", NooaExecutorSPI, priority=110, source="installed", is_factory=True
    )
    reg.declare_inject(
        "nooa",
        (InjectRequirement(service=ENVIRONMENT, capabilities=("exec", "upload")),),
    )
    task = tmp_path / "t"
    task.mkdir()
    (task / "task.yaml").write_text(
        "format: ageval.task/1\ntask_id: t\nagent_profiles:\n  - id: solver\n",
        encoding="utf-8",
    )
    (task / "run.py").write_text("async def run(ctx): pass\n", encoding="utf-8")
    (task / "evaluator.py").write_text("def evaluate(i): return {}\n", encoding="utf-8")
    try:
        with pytest.raises(ModelConfigError, match="model_extra_rejected:temperature"):
            lock_with_profiles(
                task,
                "t",
                {
                    "solver": {
                        "executor": "nooa",
                        "model": {"id": "openai/gpt-4.1-mini", "extra": {"temperature": 1}},
                        "options": {"agent": "lib.agents:FixedAnswerAgent"},
                    }
                },
            )
    finally:
        if saved is None:
            reg._injects.pop("nooa", None)
        else:
            reg._injects["nooa"] = saved


def test_factory_returns_box_executor() -> None:
    host = local_box("/nowhere")
    executor = build_executor(
        host=host,
        placement=host.placement(),
        options={"agent": "lib.agents:FixedAnswerAgent"},
        package_root=str(ROOT / "examples" / "core" / "tasks" / "nooa-host-min"),
    )
    assert isinstance(executor, NooaExecutorSPI)
    assert executor.kind == "nooa"


def test_lock_fails_when_environment_cannot_exec() -> None:
    class MuteHost:
        capabilities = EnvironmentCapabilities(upload=True)

    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(ENVIRONMENT, "mute", MuteHost, source="test", is_factory=True)
    registry.exclusive(EXECUTOR, "nooa", build_executor, source="test", is_factory=True)
    registry.declare_inject(
        "nooa",
        (InjectRequirement(service=ENVIRONMENT, capabilities=("exec", "upload")),),
    )
    with pytest.raises(InjectUnsatisfiedError, match="exec"):
        resolve(
            BindingIntent(profile_id="solver", environment="mute", executor="nooa"),
            registry,
        )


@pytest.mark.asyncio
async def test_invoke_runs_worker_through_local_exec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setenv("litellm_api_key", "sk-not-for-argv")
    package = tmp_path / "task"
    (package / "lib").mkdir(parents=True)
    (package / "lib" / "agents.py").write_text(_FIXED_AGENT, encoding="utf-8")
    (package / "lib" / "__init__.py").write_text("", encoding="utf-8")
    host = SpyHost(tmp_path / "box")
    await host.start()
    try:
        executor = build_executor(
            host=host,
            placement=host.placement(),
            options={"agent": "lib.agents:FixedAnswerAgent", "method": "run"},
            model="openai/gpt-4.1-mini",
            api_key="litellm_api_key",
            base_url="https://example.invalid/v1",
            package_root=str(package),
        )
        result = executor.invoke("hello", timeout=30)
    finally:
        await host.stop(delete=True)

    assert result.ok is True
    assert result.text == "42"
    assert result.structured == {"answer": 42}
    assert result.metadata is not None
    assert result.metadata.get("execution_location") == "attempt-container"
    assert result.metadata.get("plugin") == "nooa"
    assert host.uploads
    assert host.commands
    command, env = next(
        (cmd, env) for cmd, env in host.commands if cmd and str(cmd[-1]).lstrip().startswith("{")
    )
    assert command[0] == sys.executable
    request = json.loads(command[-1])
    assert request["agent"] == "lib.agents:FixedAnswerAgent"
    assert "sk-not-for-argv" not in json.dumps(request)
    assert "api_key" not in request
    assert env is not None
    assert env.get("OPENAI_API_KEY") == "sk-not-for-argv"
    factory_src = (ROOT / "plugins" / "nooa" / "src" / "nooa_plugin" / "factory.py").read_text(
        encoding="utf-8"
    )
    container_src = (ROOT / "plugins" / "nooa" / "src" / "nooa_plugin" / "container.py").read_text(
        encoding="utf-8"
    )
    assert "from nooa.unifiedllm" not in factory_src
    assert "get_llm_client" not in factory_src
    assert "from nooa.unifiedllm" not in container_src
    assert "get_llm_client" not in container_src
