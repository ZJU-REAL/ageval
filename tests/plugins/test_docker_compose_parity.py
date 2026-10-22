"""Attempt compose parity: service network namespace, main env, cap_add."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from ageval.application.run import _merge_attempt_declarations
from ageval.environments.protocol import BoxSpec, EnvironmentFailure
from ageval.plugins.contrib.docker.compose_parity import (
    prepare_runtime_compose,
    resolve_attempt_parity,
)
from ageval.plugins.contrib.docker.host import DockerHost
from ageval.plugins.contrib.docker.images import daemon_available, docker


def _task(tmp_path: Path, *, harbor: str | None, compose: str) -> Path:
    env = tmp_path / "environment"
    env.mkdir()
    (env / "compose.yaml").write_text(compose, encoding="utf-8")
    if harbor is not None:
        (env / "docker-compose.yaml").write_text(harbor, encoding="utf-8")
    return tmp_path


def test_harbor_main_supplies_service_env_and_cap(tmp_path: Path) -> None:
    root = _task(
        tmp_path,
        harbor="""
services:
  main:
    network_mode: "service:warehouse-api"
    environment:
      WAREHOUSE_API_URL: http://127.0.0.1:4100
      AUDIT_URL: http://127.0.0.1:4101
    cap_add:
      - SYS_PTRACE
  warehouse-api:
    image: demo
""",
        compose="services: {}\n",
    )
    parity = resolve_attempt_parity(
        task_root=root, compose_file="environment/compose.yaml", options={}
    )
    assert parity.service == "warehouse-api"
    assert parity.environment == (
        ("WAREHOUSE_API_URL", "http://127.0.0.1:4100"),
        ("AUDIT_URL", "http://127.0.0.1:4101"),
    )
    assert parity.cap_add == ("SYS_PTRACE",)


def test_env_list_and_daemon_keys(tmp_path: Path) -> None:
    root = _task(
        tmp_path,
        harbor="""
services:
  main:
    environment:
      - KV_PORT=9000
      - DOCKER_HOST=tcp://evil
    cap_add: sys_ptrace
""",
        compose="services: {}\n",
    )
    parity = resolve_attempt_parity(
        task_root=root, compose_file="environment/compose.yaml", options={}
    )
    assert parity.environment == (("KV_PORT", "9000"),)
    assert parity.cap_add == ("SYS_PTRACE",)


def test_non_service_network_mode_keeps_caps(tmp_path: Path) -> None:
    root = _task(
        tmp_path,
        harbor="""
services:
  main:
    network_mode: bridge
    cap_add: [SYS_PTRACE]
""",
        compose="services: {}\n",
    )
    parity = resolve_attempt_parity(
        task_root=root, compose_file="environment/compose.yaml", options={}
    )
    assert parity.service is None
    assert parity.cap_add == ("SYS_PTRACE",)


def test_options_override_the_harbor_file(tmp_path: Path) -> None:
    root = _task(
        tmp_path,
        harbor="""
services:
  main:
    network_mode: "service:api"
    cap_add: [SYS_PTRACE]
    environment:
      FROM_FILE: "1"
""",
        compose="services: {}\n",
    )
    parity = resolve_attempt_parity(
        task_root=root,
        compose_file="environment/compose.yaml",
        options={
            "network_mode": "service:other",
            "cap_add": ["NET_ADMIN"],
            "main_environment": {"FROM_JOB": "2"},
        },
    )
    assert parity.service == "other"
    assert parity.cap_add == ("NET_ADMIN",)
    assert parity.environment == (("FROM_JOB", "2"),)


def test_absent_compose_file_ignores_harbor_declaration(tmp_path: Path) -> None:
    root = _task(
        tmp_path,
        harbor="services:\n  main:\n    cap_add: [SYS_PTRACE]\n    network_mode: service:api\n",
        compose="services: {}\n",
    )
    parity = resolve_attempt_parity(task_root=root, compose_file=None, options={})
    assert parity.service is None
    assert parity.cap_add == ()


def test_bad_service_name_and_bare_env_fail(tmp_path: Path) -> None:
    root = _task(
        tmp_path,
        harbor="services:\n  main:\n    network_mode: 'service:../api'\n",
        compose="services: {}\n",
    )
    with pytest.raises(EnvironmentFailure, match="service name"):
        resolve_attempt_parity(task_root=root, compose_file="environment/compose.yaml", options={})
    with pytest.raises(EnvironmentFailure, match="KEY=VALUE"):
        resolve_attempt_parity(
            task_root=root,
            compose_file="environment/compose.yaml",
            options={"network_mode": "bridge", "main_environment": ["JUST_A_NAME"]},
        )


def test_runtime_compose_drops_depends_on_main(tmp_path: Path) -> None:
    source = tmp_path / "compose.yaml"
    source.write_text(
        """
services:
  api:
    image: demo
    depends_on:
      main:
        condition: service_healthy
      db:
        condition: service_started
  loadgen:
    image: demo
    depends_on:
      - main
      - db
  alone:
    image: demo
    depends_on:
      - main
""",
        encoding="utf-8",
    )
    original = source.read_text(encoding="utf-8")
    runtime = prepare_runtime_compose(source, "ageval-abc")
    assert runtime != source
    assert runtime.name == ".ageval-compose-ageval-abc.yaml"
    assert source.read_text(encoding="utf-8") == original
    loaded = yaml.safe_load(runtime.read_text(encoding="utf-8"))
    assert loaded["services"]["api"]["depends_on"] == {"db": {"condition": "service_started"}}
    assert loaded["services"]["loadgen"]["depends_on"] == ["db"]
    assert "depends_on" not in loaded["services"]["alone"]


def test_drop_main_removes_the_agent_service(tmp_path: Path) -> None:
    source = tmp_path / "docker-compose.yaml"
    source.write_text(
        "\n".join(
            [
                "services:",
                "  main:",
                "    image: agent",
                "  db:",
                "    image: demo",
                "    depends_on:",
                "      - main",
                "",
            ]
        ),
        encoding="utf-8",
    )
    runtime = prepare_runtime_compose(source, "ageval-abc", drop_main=True)
    loaded = yaml.safe_load(runtime.read_text(encoding="utf-8"))
    assert list(loaded["services"]) == ["db"]
    assert "depends_on" not in loaded["services"]["db"]
    assert "main:" in source.read_text(encoding="utf-8")


def test_main_in_the_up_file_still_supplies_parity(tmp_path: Path) -> None:
    env = tmp_path / "environment"
    env.mkdir()
    (env / "docker-compose.yaml").write_text(
        """
services:
  main:
    network_mode: "service:db"
    environment:
      API_URL: http://db:9
  db:
    image: demo
""",
        encoding="utf-8",
    )
    parity = resolve_attempt_parity(
        task_root=tmp_path,
        compose_file="environment/docker-compose.yaml",
        options={},
    )
    assert parity.service == "db"
    assert ("API_URL", "http://db:9") in parity.environment


def test_runtime_compose_keeps_the_authored_file(tmp_path: Path) -> None:
    source = tmp_path / "compose.yaml"
    source.write_text("services:\n  db:\n    image: demo\n", encoding="utf-8")
    assert prepare_runtime_compose(source, "ageval-abc") == source
    assert not (tmp_path / ".ageval-compose-ageval-abc.yaml").exists()


def test_unparseable_compose_is_left_for_compose_up(tmp_path: Path) -> None:
    source = tmp_path / "compose.yaml"
    source.write_text("services: [\n", encoding="utf-8")
    assert prepare_runtime_compose(source, "ageval-abc") == source


def test_merge_parameters_fill_gaps_and_job_wins() -> None:
    options = {"network_mode": "bridge", "user": "root"}
    _merge_attempt_declarations(
        options,
        {
            "network_mode": "service:api",
            "cap_add": ["SYS_PTRACE"],
            "main_environment": {"A": "1"},
            "active_profile": "solver",
        },
    )
    assert options["network_mode"] == "bridge"
    assert options["cap_add"] == ["SYS_PTRACE"]
    assert options["main_environment"] == {"A": "1"}
    assert "active_profile" not in options


def _spec(tmp_path: Path) -> BoxSpec:
    return BoxSpec(
        attempt_root=tmp_path / "box",
        task_root=tmp_path,
        repo_root=tmp_path,
        compose_file="environment/compose.yaml",
    )


def _patch_docker(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    def fake_docker(*args: str, timeout: float = 600.0) -> subprocess.CompletedProcess[str]:
        del timeout
        calls.append(tuple(args))
        if args[:1] == ("compose",) and "ps" in args:
            return subprocess.CompletedProcess(args, 0, stdout="sidecar-1\n", stderr="")
        if args[:1] == ("run",):
            return subprocess.CompletedProcess(args, 0, stdout="attempt-1\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "ageval.plugins.contrib.docker.host.resolve_image",
        lambda **_kwargs: ("example:latest", "sha256:abc"),
    )
    monkeypatch.setattr("ageval.plugins.contrib.docker.host.docker", fake_docker)
    return calls


def _run_call(calls: list[tuple[str, ...]]) -> tuple[str, ...]:
    return next(call for call in calls if call[:1] == ("run",))


@pytest.mark.asyncio
async def test_start_uses_container_network_env_and_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _task(
        tmp_path,
        harbor="""
services:
  main:
    network_mode: "service:api"
    environment:
      WAREHOUSE_API_URL: http://127.0.0.1:4100
    cap_add: [SYS_PTRACE]
""",
        compose="""
services:
  api:
    image: demo
    depends_on:
      main:
        condition: service_healthy
""",
    )
    calls = _patch_docker(monkeypatch)
    host = DockerHost(spec=_spec(tmp_path), options={})
    await host.start()
    try:
        run = _run_call(calls)
        network = run[run.index("--network") + 1]
        assert network == "container:sidecar-1"
        assert "--cap-add" in run
        assert "SYS_PTRACE" in run
        assert "WAREHOUSE_API_URL=http://127.0.0.1:4100" in run
        ps = next(call for call in calls if call[:1] == ("compose",) and "ps" in call)
        assert ps[-1] == "api"
        up = next(call for call in calls if call[:1] == ("compose",) and "up" in call)
        compose_file = up[up.index("-f") + 1]
        assert Path(compose_file).name.startswith(".ageval-compose-")
    finally:
        await host.stop(delete=True)
    assert not list(tmp_path.glob("environment/.ageval-compose-*.yaml"))


@pytest.mark.asyncio
async def test_start_without_service_mode_joins_project_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _task(tmp_path, harbor=None, compose="services:\n  db:\n    image: demo\n")
    calls = _patch_docker(monkeypatch)
    host = DockerHost(spec=_spec(tmp_path), options={})
    await host.start()
    await host.stop(delete=True)
    run = _run_call(calls)
    network = run[run.index("--network") + 1]
    assert network.endswith("_default")
    assert "--cap-add" not in run
    assert not any(call[:1] == ("compose",) and "ps" in call for call in calls)


@pytest.mark.asyncio
async def test_service_network_rejects_egress_llm(tmp_path: Path) -> None:
    _task(tmp_path, harbor=None, compose="services:\n  api:\n    image: demo\n")
    host = DockerHost(
        spec=_spec(tmp_path),
        options={"network_mode": "service:api", "egress": "llm"},
    )
    with pytest.raises(EnvironmentFailure, match="egress: llm"):
        await host.start()


def _skip_without_docker() -> None:
    if os.environ.get("AGEVAL_SKIP_DOCKER") == "1":
        pytest.skip("AGEVAL_SKIP_DOCKER=1")
    if not daemon_available():
        pytest.skip("docker daemon is not reachable")


@pytest.mark.asyncio
async def test_real_attempt_shares_sidecar_namespace_and_cap(tmp_path: Path) -> None:
    """Inspect a real container: localhost, SYS_PTRACE, and the declared env."""
    _skip_without_docker()
    _task(
        tmp_path,
        harbor="""
services:
  main:
    network_mode: "service:api"
    environment:
      WAREHOUSE_API_URL: http://127.0.0.1:4100
    cap_add:
      - SYS_PTRACE
""",
        compose="""
services:
  api:
    image: python:3.12-slim
    command: ["python", "-m", "http.server", "18765", "--bind", "127.0.0.1"]
""",
    )
    host = DockerHost(
        spec=_spec(tmp_path),
        options={"image": "python:3.12-slim"},
    )
    try:
        await host.preflight()
        await host.start()
        assert host._container is not None
        inspected = docker(
            "inspect",
            host._container,
            "--format",
            "{{.HostConfig.NetworkMode}}|{{json .HostConfig.CapAdd}}",
        )
        assert inspected.returncode == 0, inspected.stderr
        network_mode, caps = (inspected.stdout or "").strip().split("|", 1)
        assert network_mode.startswith("container:")
        assert "SYS_PTRACE" in caps
        env = await host.exec(
            ["python", "-c", "import os; print(os.environ['WAREHOUSE_API_URL'])"],
            timeout_sec=30,
        )
        assert env.ok, env.stderr or env.stdout
        assert "http://127.0.0.1:4100" in env.stdout
        reached = False
        last = ""
        for _ in range(20):
            probe = await host.exec(
                [
                    "python",
                    "-c",
                    "import urllib.request; "
                    "print(urllib.request.urlopen('http://127.0.0.1:18765/', timeout=2).status)",
                ],
                timeout_sec=15,
            )
            last = probe.stdout or probe.stderr
            if probe.ok and "200" in probe.stdout:
                reached = True
                break
            await asyncio.sleep(0.25)
        assert reached, last
    finally:
        await host.stop(delete=True)
