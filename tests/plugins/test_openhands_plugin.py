"""OpenHands invoke stays on the environment Protocol and a trajectory file."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ageval.environments.protocol import (
    WORKSPACE_PATH,
    EnvironmentCapabilities,
    ExecResult,
    Placement,
)
from ageval.plugins.defaults import register_defaults
from ageval.plugins.errors import ExtensionMaterializeError, InjectUnsatisfiedError
from ageval.plugins.manifest import load_manifest
from ageval.plugins.protocol import BindingIntent, InjectRequirement
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.slots import ENVIRONMENT, EXECUTOR

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "openhands" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from openhands_plugin.container import BOX_INSTRUCTION, BOX_WORKER  # noqa: E402
from openhands_plugin.factory import OpenHandsExecutorSPI, build_executor  # noqa: E402
from openhands_plugin.hooks import trajectory_collect  # noqa: E402
from openhands_plugin.pin import SDK_VERSION  # noqa: E402
from openhands_plugin.trajectory import to_ageval_trajectory_events  # noqa: E402

_PROMPT = "summarize the three jsonl files into aggregates.json — token not-in-argv"


class FakeHost:
    """Records exec/upload and plants the trajectory file the worker would write."""

    python_command = ("python3",)
    capabilities = EnvironmentCapabilities(exec=True, upload=True, download=True)

    def __init__(self, *, sdk_present: bool = True, pip_ok: bool = True) -> None:
        self.sdk_present = sdk_present
        self.pip_ok = pip_ok
        self.commands: list[tuple[list[str], dict[str, str] | None, float | None]] = []
        self.uploads: list[tuple[str, str]] = []
        self.files: dict[str, bytes] = {}
        self.probes = 0

    def placement(self) -> Placement:
        return Placement(target_id="box", workdir=WORKSPACE_PATH)

    def visible_path(self, box_path: str) -> str:
        return box_path

    async def upload(self, source: Path, dest: str) -> None:
        text = Path(source).read_text(encoding="utf-8")
        self.uploads.append((str(dest), text))
        self.files[str(dest)] = text.encode()

    async def download(self, source: str, dest: Path) -> None:
        payload = self.files.get(str(source))
        if payload is None:
            raise FileNotFoundError(source)
        Path(dest).write_bytes(payload)

    async def exec(self, command, **kwargs: Any):  # type: ignore[no-untyped-def]
        argv = [str(part) for part in command]
        env = kwargs.get("env")
        timeout = kwargs.get("timeout_sec")
        self.commands.append((argv, dict(env) if isinstance(env, dict) else None, timeout))
        joined = " ".join(argv)
        if "import openhands.sdk" in joined:
            self.probes += 1
            present = self.sdk_present or (self.pip_ok and self.probes > 1)
            return ExecResult(0 if present else 1, stderr="" if present else "missing")
        if "-m" in argv and "pip" in argv:
            return ExecResult(0 if self.pip_ok else 1, stderr="" if self.pip_ok else "no pip")
        if "ageval_executor_openhands.py" in joined:
            trajectory = argv[argv.index("--trajectory") + 1]
            body = {
                "schema": "openhands.trajectory/1",
                "model": (env or {}).get("OH_MODEL", "m"),
                "ok": True,
                "text": '{"answer": 1}',
                "error": None,
                "steps": [
                    {"type": "user_message", "content": "from-file"},
                    {
                        "type": "tool_call",
                        "tool_call_id": "call-1",
                        "name": "terminal",
                        "arguments": {"command": "ls"},
                    },
                    {
                        "type": "tool_result",
                        "tool_call_id": "call-1",
                        "name": "terminal",
                        "content": "aggregates.json",
                    },
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            }
            self.files[trajectory] = (json.dumps(body) + "\n").encode()
            return ExecResult(0)
        return ExecResult(0)


def test_manifest_injects_exec_upload_download() -> None:
    manifest = load_manifest(ROOT / "plugins" / "openhands")
    assert manifest.plugin_id == "openhands"
    assert manifest.description
    row = manifest.inject[0]
    assert row.service == "environment"
    assert set(row.capabilities) == {"exec", "upload", "download"}
    assert manifest.image_layers == "docker/Dockerfile.bake"


def test_bake_pins_the_packaged_version() -> None:
    bake = (ROOT / "plugins" / "openhands" / "docker" / "Dockerfile.bake").read_text(
        encoding="utf-8"
    )
    assert f"openhands-sdk=={SDK_VERSION}" in bake
    assert f"openhands-tools=={SDK_VERSION}" in bake


def test_worker_stays_on_a_local_workspace() -> None:
    text = (ROOT / "plugins" / "openhands" / "worker" / "ageval_executor_openhands.py").read_text(
        encoding="utf-8"
    )
    assert "LocalWorkspace(" in text
    assert "RemoteWorkspace(" not in text


def test_factory_rejects_a_version_range() -> None:
    host = FakeHost()
    with pytest.raises(ExtensionMaterializeError, match="openhands_version_invalid"):
        build_executor(
            host=host,
            placement=host.placement(),
            options={"version": ">=1.56.0"},
        )


def test_factory_returns_box_executor() -> None:
    host = FakeHost()
    executor = build_executor(host=host, placement=host.placement(), options={})
    assert isinstance(executor, OpenHandsExecutorSPI)
    assert executor.kind == "openhands"
    assert executor.options.version == SDK_VERSION


def test_lock_rejects_unknown_model_extra(tmp_path: Path) -> None:
    from tests.helpers.lock import lock_with_profiles

    from ageval.model.errors import ModelConfigError
    from ageval.plugins.bootstrap import ensure_bootstrapped

    reg = ensure_bootstrapped()
    saved = reg._injects.get("openhands")
    reg.exclusive(
        EXECUTOR,
        "openhands",
        OpenHandsExecutorSPI,
        priority=110,
        source="installed",
        is_factory=True,
    )
    reg.declare_inject(
        "openhands",
        (
            InjectRequirement(
                service=ENVIRONMENT,
                capabilities=("exec", "upload", "download"),
            ),
        ),
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
                        "executor": "openhands",
                        "model": {"id": "openai/gpt-4.1-mini", "extra": {"temperature": 1}},
                    }
                },
            )
    finally:
        if saved is None:
            reg._injects.pop("openhands", None)
        else:
            reg._injects["openhands"] = saved


def test_lock_fails_when_environment_cannot_exec() -> None:
    class MuteHost:
        capabilities = EnvironmentCapabilities(upload=True, download=True)

    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(ENVIRONMENT, "mute", MuteHost, source="test", is_factory=True)
    registry.exclusive(EXECUTOR, "openhands", build_executor, source="test", is_factory=True)
    registry.declare_inject(
        "openhands",
        (
            InjectRequirement(
                service=ENVIRONMENT,
                capabilities=("exec", "upload", "download"),
            ),
        ),
    )
    with pytest.raises(InjectUnsatisfiedError, match="exec"):
        resolve(
            BindingIntent(profile_id="solver", environment="mute", executor="openhands"),
            registry,
        )


@pytest.mark.asyncio
async def test_invoke_uploads_instruction_and_reads_trajectory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("litellm_api_key", "sk-not-for-argv")
    host = FakeHost()
    executor = build_executor(
        host=host,
        placement=host.placement(),
        options={"max_iterations": 7},
        model={
            "id": "openai/glm-5.2",
            "api": "chat",
            "reasoning": {"effort": "max"},
        },
        api_key="litellm_api_key",
        base_url="https://example.invalid/v1",
    )
    result = executor.invoke(_PROMPT, timeout=30, collect_dir=str(tmp_path / "raw"))

    assert result.ok is True
    assert result.structured == {"answer": 1}
    assert result.metadata is not None
    assert result.metadata.get("execution_location") == "attempt-container"
    assert result.metadata.get("sdk_version") == SDK_VERSION
    assert result.usage.prompt_tokens == 3
    uploaded = dict(host.uploads)
    assert uploaded[BOX_INSTRUCTION] == _PROMPT
    assert BOX_WORKER in uploaded
    worker_cmds = [
        cmd for cmd, _, _ in host.commands if "ageval_executor_openhands.py" in " ".join(cmd)
    ]
    assert len(worker_cmds) == 1
    assert _PROMPT not in worker_cmds[0]
    assert "sk-not-for-argv" not in json.dumps(worker_cmds[0])
    pip_cmds = [cmd for cmd, _, _ in host.commands if "pip" in cmd]
    assert pip_cmds == []
    _argv, env, _timeout = next(
        item for item in host.commands if "ageval_executor_openhands.py" in " ".join(item[0])
    )
    assert env is not None
    assert env.get("OPENAI_API_KEY") == "sk-not-for-argv"
    assert env.get("OH_REASONING_EFFORT") == "max"
    assert env.get("OH_MAX_ITERATIONS") == "7"
    assert "api_key" not in env
    kinds = [event["kind"] for event in result.events]
    assert "tool" in kinds
    saved = (tmp_path / "raw" / "openhands_trajectory.json").read_text(encoding="utf-8")
    assert "terminal" in saved
    assert "sk-not-for-argv" not in saved


@pytest.mark.asyncio
async def test_missing_sdk_installs_the_pin_or_fails_closed() -> None:
    host = FakeHost(sdk_present=False, pip_ok=True)
    executor = build_executor(host=host, placement=host.placement(), model="openai/gpt-4.1-mini")
    result = executor.invoke("hi", timeout=15)
    assert result.ok is True
    pip = next(cmd for cmd, _, _ in host.commands if "pip" in cmd)
    assert f"openhands-sdk=={SDK_VERSION}" in pip
    assert f"openhands-tools=={SDK_VERSION}" in pip
    assert "docker" not in " ".join(pip)
    timeout = next(item[2] for item in host.commands if "pip" in item[0])
    assert timeout == 600.0

    broken = FakeHost(sdk_present=False, pip_ok=False)
    executor = build_executor(
        host=broken, placement=broken.placement(), model="openai/gpt-4.1-mini"
    )
    failed = executor.invoke("hi", timeout=15)
    assert failed.ok is False
    assert failed.error == "openhands_sdk_install_failed"
    assert not any("ageval_executor_openhands.py" in " ".join(cmd) for cmd, _, _ in broken.commands)


def test_trajectory_maps_steps_and_leaves_foreign_events() -> None:
    mapped = to_ageval_trajectory_events(
        (
            {"type": "assistant_message", "content": "look"},
            {
                "type": "tool_call",
                "tool_call_id": "c1",
                "name": "terminal",
                "arguments": {"command": "ls"},
            },
        )
    )
    assert mapped[0]["source"] == "openhands"
    assert mapped[0]["schema"] == "ageval.trajectory.event/1"
    assert mapped[1]["kind"] == "tool"
    assert mapped[1]["phase"] == "start"
    assert mapped[1]["args"] == {"command": "ls"}


@pytest.mark.asyncio
async def test_trajectory_collect_stamps_own_source_only() -> None:
    async def nxt(value: Any) -> Any:
        return value

    foreign = ({"schema": "ageval.trajectory.event/1", "source": "acp", "kind": "text"},)
    out = await trajectory_collect(None, {"events": foreign, "metadata": {}}, nxt)
    assert out["events"] == foreign
    assert "trajectory_source" not in out["metadata"]

    native = ({"type": "assistant_message", "content": "done"},)
    mapped = await trajectory_collect(None, {"events": native, "metadata": {}}, nxt)
    assert mapped["metadata"]["trajectory_source"] == "openhands"
    assert mapped["events"][0]["source"] == "openhands"


def test_worker_writes_a_trajectory_without_the_sdk(tmp_path: Path) -> None:
    stub = tmp_path / "stub"
    sdk = stub / "openhands" / "sdk"
    preset = stub / "openhands" / "tools" / "preset"
    sdk.mkdir(parents=True)
    preset.mkdir(parents=True)
    (stub / "openhands" / "__init__.py").write_text("", encoding="utf-8")
    (stub / "openhands" / "tools" / "__init__.py").write_text("", encoding="utf-8")
    (preset / "__init__.py").write_text("", encoding="utf-8")
    (sdk / "__init__.py").write_text(
        "\n".join(
            [
                "class LocalWorkspace:",
                "    def __init__(self, *, working_dir):",
                "        self.working_dir = working_dir",
                "class MessageEvent:",
                "    def __init__(self, source, content):",
                "        self.source = source",
                "        self.llm_message = type('M', (), {'content': content})()",
                "class ActionEvent:",
                "    def __init__(self):",
                "        self.tool_call_id = 'call-1'",
                "        self.tool_name = 'terminal'",
                "        self.action = type('A', (), {",
                "            'model_dump': lambda self: {'command': 'ls', 'kind': 'x'},",
                "        })()",
                "class ObservationEvent:",
                "    def __init__(self):",
                "        self.tool_call_id = 'call-1'",
                "        self.tool_name = 'terminal'",
                "        self.observation = type('O', (), {'content': 'listed'})()",
                "class _Usage:",
                "    prompt_tokens = 2",
                "    completion_tokens = 3",
                "    cache_read_tokens = 0",
                "class _Metrics:",
                "    accumulated_token_usage = _Usage()",
                "    accumulated_cost = 0.0",
                "class LLM:",
                "    def __init__(self, **kwargs):",
                "        self.kwargs = kwargs",
                "        self.metrics = _Metrics()",
                "class Agent:",
                "    def __init__(self, **kwargs):",
                "        self.kwargs = kwargs",
                "class Conversation:",
                "    def __init__(self, agent, *, workspace, max_iteration_per_run, visualizer):",
                "        assert type(workspace).__name__ == 'LocalWorkspace'",
                "        self.state = type('S', (), {'events': []})()",
                "        self.max_iteration_per_run = max_iteration_per_run",
                "    def send_message(self, text):",
                "        self.state.events.append(MessageEvent('user', text))",
                "        self.state.events.append(ActionEvent())",
                "        self.state.events.append(ObservationEvent())",
                "        self.state.events.append(MessageEvent('agent', 'wrote aggregates'))",
                "    def run(self):",
                "        return None",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (sdk / "conversation.py").write_text(
        "def get_agent_final_response(events):\n    return 'wrote aggregates'\n",
        encoding="utf-8",
    )
    (preset / "default.py").write_text(
        "def get_default_tools(*, enable_browser=True):\n"
        "    assert enable_browser is False\n"
        "    return ['terminal']\n",
        encoding="utf-8",
    )
    instruction = tmp_path / "instruction.md"
    instruction.write_text("count the rows\n", encoding="utf-8")
    trajectory = tmp_path / "trajectory.json"
    worker = ROOT / "plugins" / "openhands" / "worker" / "ageval_executor_openhands.py"
    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(stub),
        "OH_MODEL": "openai/gpt-4.1-mini",
        "OPENAI_API_KEY": "sk-not-for-file",
        "OPENAI_BASE_URL": "https://example.invalid/v1",
        "OH_REASONING_EFFORT": "max",
        "OH_MAX_ITERATIONS": "4",
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(worker),
            "--instruction-file",
            str(instruction),
            "--trajectory",
            str(trajectory),
            "--workdir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    document = json.loads(trajectory.read_text(encoding="utf-8"))
    assert document["schema"] == "openhands.trajectory/1"
    assert document["ok"] is True
    assert document["text"] == "wrote aggregates"
    assert document["steps"][0]["type"] == "user_message"
    assert document["steps"][0]["content"] == "count the rows\n"
    assert document["steps"][1]["type"] == "tool_call"
    assert document["steps"][1]["arguments"] == {"command": "ls"}
    assert document["usage"]["prompt_tokens"] == 2
    assert "sk-not-for-file" not in trajectory.read_text(encoding="utf-8")
    assert str(instruction) in proc.args
    assert "count the rows" not in proc.args
