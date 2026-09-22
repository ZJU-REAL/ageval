"""miniswe executor talks to the box only through the environment Protocol."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.environments.protocol import (
    WORKSPACE_PATH,
    EnvironmentCapabilities,
    ExecResult,
    Placement,
)
from ageval.plugins.contrib.local.host import LocalHost
from ageval.plugins.defaults import register_defaults
from ageval.plugins.errors import InjectUnsatisfiedError
from ageval.plugins.protocol import BindingIntent, InjectRequirement
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.slots import ENVIRONMENT, EXECUTOR

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "miniswe" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from miniswe_plugin.env import ProtocolEnv  # noqa: E402
from miniswe_plugin.factory import (  # noqa: E402
    MinisweExecutorSPI,
    _load_official_mini_config,
    build_executor,
)
from miniswe_plugin.hooks import image_contribute, trajectory_collect  # noqa: E402
from miniswe_plugin.trajectory import SCHEMA, to_ageval_trajectory_events  # noqa: E402


def _placement() -> Placement:
    return Placement(target_id="box", user="10001:10001", workdir=WORKSPACE_PATH)


def _isolated_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *plugin_ids: str
) -> dict[str, str]:
    from ageval.plugins import bootstrap as boot
    from ageval.plugins.registry import reset_global_registry
    from ageval.plugins.store import install_from_path

    home = tmp_path / "ageval-home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()
    for plugin_id in plugin_ids:
        install_from_path(ROOT / "plugins" / plugin_id)
    env = os.environ.copy()
    env["AGEVAL_HOME"] = str(home)
    env["litellm_api_key"] = "sk-lock-must-not-see"
    env["litellm_base_url"] = "https://example.invalid/v1"
    return env


def test_package_has_no_docker_exec_or_container_id() -> None:
    root = ROOT / "plugins" / "miniswe"
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
    assert offenders == []


def test_factory_stores_host_and_placement() -> None:
    host = SimpleNamespace(kind="local")
    placement = _placement()
    spi = build_executor(host=host, placement=placement, model="openai/x")
    assert spi.host is host
    assert spi.placement is placement
    assert isinstance(spi, MinisweExecutorSPI)


def test_protocol_env_calls_host_exec() -> None:
    recorded: list[dict[str, object]] = []

    class SpyHost:
        kind = "docker"

        async def exec(self, command, **kwargs):  # noqa: ANN001
            recorded.append({"command": list(command), **kwargs})
            return ExecResult(exit_code=0, stdout="ok\n", stderr="")

    env = ProtocolEnv(host=SpyHost(), placement=_placement(), timeout=5)
    out = env.execute({"command": "echo hi"})
    assert out["returncode"] == 0
    assert out["output"] == "ok\n"
    assert recorded[0]["command"] == ["bash", "-lc", "echo hi"]
    assert recorded[0]["cwd"] == WORKSPACE_PATH
    assert recorded[0]["user"] == "10001:10001"


def test_official_mini_yaml_loads() -> None:
    data = _load_official_mini_config()
    agent = data.get("agent") or {}
    assert agent.get("system_template")
    assert "{{task}}" in str(agent.get("instance_template") or "")


def test_invalid_step_limit() -> None:
    from ageval.plugins.errors import ExtensionMaterializeError

    with pytest.raises(ExtensionMaterializeError, match="step_limit"):
        build_executor(
            host=SimpleNamespace(kind="local"),
            placement=_placement(),
            options={"step_limit": -1},
        )


def test_reasoning_effort_forwarded_to_litellm_kwargs() -> None:
    spi = build_executor(
        host=SimpleNamespace(kind="local"),
        placement=_placement(),
        options={"reasoning_effort": "max"},
        model="openai/dashscope/qwen3.8-max",
    )
    assert spi.reasoning_effort == "max"
    kwargs = spi._litellm_model_kwargs(key="sk-x", base="https://example.invalid/v1")
    assert kwargs["reasoning_effort"] == "max"
    assert kwargs["drop_params"] is True
    omitted = build_executor(
        host=SimpleNamespace(kind="local"),
        placement=_placement(),
        model="openai/x",
    )
    assert omitted.reasoning_effort is None
    assert "reasoning_effort" not in omitted._litellm_model_kwargs(key=None, base=None)


def test_invalid_reasoning_effort() -> None:
    from ageval.plugins.errors import ExtensionMaterializeError

    with pytest.raises(ExtensionMaterializeError, match="reasoning_effort"):
        build_executor(
            host=SimpleNamespace(kind="local"),
            placement=_placement(),
            options={"reasoning_effort": 1},
        )


def test_extra_body_merges_into_litellm_kwargs() -> None:
    spi = build_executor(
        host=SimpleNamespace(kind="local"),
        placement=_placement(),
        options={
            "reasoning_effort": "low",
            "step_limit": 12,
            "extra_body": {
                "reasoning": {"max_tokens": 2000},
                "provider": {"order": ["Together"]},
            },
        },
        model="openrouter/openai/gpt-4o",
    )
    kwargs = spi._litellm_model_kwargs(key="sk-x", base="https://openrouter.ai/api/v1")
    assert kwargs["reasoning"] == {"max_tokens": 2000}
    assert kwargs["provider"] == {"order": ["Together"]}
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["drop_params"] is True
    assert "step_limit" not in kwargs
    omitted = build_executor(
        host=SimpleNamespace(kind="local"),
        placement=_placement(),
        model="openai/x",
    )
    assert omitted.extra_body == {}
    assert "reasoning" not in omitted._litellm_model_kwargs(key=None, base=None)


def test_extra_body_overrides_reasoning_effort() -> None:
    spi = build_executor(
        host=SimpleNamespace(kind="local"),
        placement=_placement(),
        options={
            "reasoning_effort": "low",
            "extra_body": {"reasoning_effort": "high"},
        },
        model="openai/x",
    )
    kwargs = spi._litellm_model_kwargs(key=None, base=None)
    assert kwargs["reasoning_effort"] == "high"


def test_invalid_extra_body() -> None:
    from ageval.plugins.errors import ExtensionMaterializeError

    with pytest.raises(ExtensionMaterializeError, match="extra_body_invalid"):
        build_executor(
            host=SimpleNamespace(kind="local"),
            placement=_placement(),
            options={"extra_body": ["reasoning"]},
        )
    with pytest.raises(ExtensionMaterializeError, match="extra_body_reserved"):
        build_executor(
            host=SimpleNamespace(kind="local"),
            placement=_placement(),
            options={"extra_body": {"api_key": "sk-leak", "model": "other"}},
        )


def test_offline_invoke_does_not_import_vendor(monkeypatch: object) -> None:
    monkeypatch.setenv("AGEVAL_OFFLINE_AGENT", "1")  # type: ignore[attr-defined]
    spi = MinisweExecutorSPI(
        host=SimpleNamespace(kind="local"),
        placement=_placement(),
        model="openai/x",
        api_key="litellm_api_key",
    )
    result = spi.invoke("ping")
    assert result.ok is False
    assert result.error == "offline_forced"


def test_lock_fails_when_environment_cannot_exec() -> None:
    class MuteHost:
        capabilities = EnvironmentCapabilities(upload=True)

    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(ENVIRONMENT, "mute", MuteHost, source="test", is_factory=True)
    registry.exclusive(EXECUTOR, "miniswe", build_executor, source="test", is_factory=True)
    registry.declare_inject(
        "miniswe",
        (InjectRequirement(service=ENVIRONMENT, capabilities=("exec",)),),
    )
    with pytest.raises(InjectUnsatisfiedError, match="exec"):
        resolve(
            BindingIntent(profile_id="solver", environment="mute", executor="miniswe"),
            registry,
        )


def test_lock_records_inject_when_box_can_exec() -> None:
    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(ENVIRONMENT, "local", LocalHost, source="test", is_factory=True)
    registry.exclusive(EXECUTOR, "miniswe", build_executor, source="test", is_factory=True)
    registry.declare_inject(
        "miniswe",
        (InjectRequirement(service=ENVIRONMENT, capabilities=("exec",)),),
    )
    graph = resolve(
        BindingIntent(profile_id="solver", environment="local", executor="miniswe"),
        registry,
    )
    rows = graph.injects["miniswe"]
    assert rows[0].service == "environment"
    assert set(rows[0].capabilities) == {"exec"}


def test_lock_cli_miniswe_profile_records_inject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _isolated_home(tmp_path, monkeypatch, "miniswe")
    profiles = tmp_path / "profiles.miniswe.yaml"
    profiles.write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                "environment: docker",
                "agent_profiles:",
                "  solver:",
                "    executor: miniswe",
                "    extensions:",
                "      - plugin: miniswe",
                "        options:",
                "          step_limit: 20",
                "          cost_limit: 0",
                "          cmd_timeout: 60",
                "      - plugin: docker",
                "    model: openai/glm-5.3",
                "    api_key: ${litellm_api_key}",
                "    base_url: ${litellm_base_url}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
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
    assert solver["slots"]["executor"]["plugin"] == "miniswe"
    inject = (solver.get("inject") or {}).get("miniswe") or []
    caps = next(
        tuple(row.get("capabilities") or ())
        for row in inject
        if row.get("service") == "environment"
    )
    assert set(caps) == {"exec"}
    assert "sk-lock-must-not-see" not in json.dumps(data)


def test_messages_map_to_layer_b() -> None:
    mapped = to_ageval_trajectory_events(
        (
            {"role": "user", "content": "fix the bug"},
            {
                "role": "assistant",
                "content": "I will list files",
                "extra": {"actions": [{"command": "ls", "tool_call_id": "call_ls"}]},
            },
            {
                "role": "tool",
                "tool_call_id": "call_ls",
                "content": "<returncode>0</returncode>\n<output>\na.py\n</output>",
                "extra": {"returncode": 0, "raw_output": "a.py\n"},
            },
            {"role": "exit", "content": "Submitted", "extra": {"exit_status": "Submitted"}},
        )
    )
    assert all(e.get("schema") == SCHEMA for e in mapped)
    assert all(e.get("source") == "miniswe" for e in mapped)
    assert not any(e.get("type") == "session_update" for e in mapped)
    start = next(e for e in mapped if e.get("kind") == "tool" and e.get("phase") == "start")
    assert start["tool_call_id"] == "call_ls"
    assert start["function_name"] == "bash"
    assert start["args"] == {"command": "ls"}
    assert start["status"] == "pending"
    update = next(e for e in mapped if e.get("kind") == "tool" and e.get("phase") == "update")
    assert update["tool_call_id"] == "call_ls"
    assert update["status"] == "completed"
    assert "a.py" in str(update.get("content") or "")


def test_reasoning_content_folds_to_thought_not_agent() -> None:
    from ageval.evidence.trajectory import turn_rows

    mapped = to_ageval_trajectory_events(
        (
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "The user wants me to list files. I'll run ls.",
                "tool_calls": [
                    {
                        "id": "call_ls",
                        "function": {"name": "bash", "arguments": '{"command": "ls -la"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_ls",
                "content": "ok",
                "extra": {"returncode": 0, "raw_output": "ok"},
            },
        ),
        session_id="ageval-solver-x",
    )
    assert [e.get("channel") for e in mapped if e.get("kind") == "text"] == ["thought"]
    lines = turn_rows(
        prompt="list files",
        events=mapped,
        final_text="",
        structured=None,
        usage=None,
        ok=True,
        error=None,
        metadata={"plugin": "miniswe", "profile_id": "solver"},
    )
    thoughts = [x for x in lines if x.get("part") == "thought"]
    agents = [
        x
        for x in lines
        if x.get("type") == "turn" and x.get("role") == "assistant" and x.get("part") != "thought"
    ]
    assert len(thoughts) == 1
    assert "list files" in thoughts[0]["content"]
    assert agents == []
    assert any(x["type"] == "tool_call" for x in lines)


def test_mapped_events_fold_to_viewer_tool_call() -> None:
    from ageval.evidence.trajectory import turn_rows

    mapped = to_ageval_trajectory_events(
        (
            {
                "role": "assistant",
                "content": "listing",
                "extra": {"actions": [{"command": "ls", "tool_call_id": "call_ls"}]},
            },
            {
                "role": "tool",
                "tool_call_id": "call_ls",
                "content": "ok",
                "extra": {"returncode": 0, "raw_output": "ok"},
            },
        ),
        session_id="ageval-solver-x",
    )
    lines = turn_rows(
        prompt="fix the bug",
        events=mapped,
        final_text="",
        structured=None,
        usage=None,
        ok=True,
        error=None,
        metadata={"plugin": "miniswe", "profile_id": "solver"},
    )
    types = [x["type"] for x in lines]
    assert "tool_call" in types
    assert "observation" in types
    tool = next(x for x in lines if x["type"] == "tool_call")
    assert tool["tool_call_id"] == "call_ls"
    assert tool["function_name"] == "bash"
    assert tool["args"] == {"command": "ls"}
    obs = next(x for x in lines if x["type"] == "observation")
    assert obs["tool_call_id"] == "call_ls"
    assert "ok" in str(obs.get("content") or obs.get("raw_output") or "")


@pytest.mark.asyncio
async def test_image_contribute_declares_plugin() -> None:
    async def nxt(value: object) -> object:
        return value

    out = await image_contribute(None, [], nxt)
    assert out == [{"plugin": "miniswe"}]


@pytest.mark.asyncio
async def test_trajectory_collect_stamps_own_source() -> None:
    events = to_ageval_trajectory_events(({"role": "user", "content": "hi"},))

    async def nxt(value: object) -> object:
        return value

    out = await trajectory_collect(None, {"events": events, "metadata": {}}, nxt)
    assert out["metadata"]["trajectory_source"] == "miniswe"
