"""docker run flags for task cpus / memory / gpus, and the fail-closed GPU path."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from ageval.environments.protocol import BoxSpec, EnvironmentFailure
from ageval.plugins.contrib.docker.host import DockerHost
from ageval.plugins.contrib.docker.resources import (
    DockerRunResources,
    GpuDevice,
    docker_run_resource_args,
    parse_gpu_inventory,
    query_gpu_inventory,
    sidecar_resource_overlay,
)


def test_tb4_style_cpus_and_memory_flags() -> None:
    args = docker_run_resource_args(
        DockerRunResources(cpus=2, memory_mb=4096, gpus=0, gpu_types=()),
        (),
    )
    assert args == ["--cpus", "2", "--memory", "4096m"]


def test_unset_resources_add_no_flags() -> None:
    assert docker_run_resource_args(DockerRunResources(), ()) == []


def test_matching_gpu_type_pins_the_device_index() -> None:
    inventory = (
        GpuDevice(0, "NVIDIA A100-SXM4-80GB"),
        GpuDevice(1, "NVIDIA H100 80GB HBM3"),
    )
    args = docker_run_resource_args(
        DockerRunResources(gpus=1, gpu_types=("H100",)),
        inventory,
    )
    assert args == ["--gpus", "device=1"]


def test_gpu_count_without_types_uses_count() -> None:
    inventory = (GpuDevice(0, "NVIDIA A100"), GpuDevice(1, "NVIDIA A100"))
    args = docker_run_resource_args(DockerRunResources(gpus=1), inventory)
    assert args == ["--gpus", "count=1"]


def test_missing_or_mismatched_gpu_is_typed() -> None:
    with pytest.raises(EnvironmentFailure) as missing:
        docker_run_resource_args(DockerRunResources(gpus=1, gpu_types=("H100",)), ())
    assert missing.value.kind == "environment_gpu_unavailable"
    with pytest.raises(EnvironmentFailure) as mismatched:
        docker_run_resource_args(
            DockerRunResources(gpus=1, gpu_types=("H100",)),
            (GpuDevice(0, "NVIDIA A100"),),
        )
    assert mismatched.value.kind == "environment_gpu_unavailable"


def test_parse_nvidia_smi_csv() -> None:
    text = "0, NVIDIA H100 80GB HBM3\n1, NVIDIA A100-SXM4-80GB\n"
    assert parse_gpu_inventory(text) == (
        GpuDevice(0, "NVIDIA H100 80GB HBM3"),
        GpuDevice(1, "NVIDIA A100-SXM4-80GB"),
    )


def test_missing_nvidia_smi_is_gpu_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    monkeypatch.setattr("ageval.plugins.contrib.docker.resources.subprocess.run", boom)
    with pytest.raises(EnvironmentFailure) as caught:
        query_gpu_inventory()
    assert caught.value.kind == "environment_gpu_unavailable"


def test_sidecar_overlay_copies_declared_limits_only() -> None:
    overlay = sidecar_resource_overlay(
        {
            "services": {
                "loadgen": {"image": "busybox", "cpus": 1.0, "mem_limit": "512m"},
                "plain": {"image": "busybox"},
                "already": {
                    "image": "busybox",
                    "cpus": 2,
                    "deploy": {"resources": {"limits": {"cpus": "2"}}},
                },
            }
        }
    )
    assert overlay == {
        "services": {
            "loadgen": {"deploy": {"resources": {"limits": {"cpus": "1", "memory": "512m"}}}},
        }
    }


def test_created_container_argv_carries_tb4_limits(tmp_path: Path) -> None:
    bare = _start(tmp_path / "bare", {})
    limited = _start(
        tmp_path / "limited",
        {"cpus": 2, "memory_mb": 4096, "gpus": 0, "gpu_types": []},
    )
    assert "--cpus" not in bare
    assert "--memory" not in bare
    assert "--gpus" not in bare
    assert _shape(bare) == _shape(_start(tmp_path / "zeros", {"gpus": 0, "gpu_types": []}))
    assert limited[limited.index("--cpus") + 1] == "2"
    assert limited[limited.index("--memory") + 1] == "4096m"
    assert "--gpus" not in limited


def test_start_fails_closed_without_calling_docker_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, ...]] = []
    _patch_docker(monkeypatch, calls)
    monkeypatch.setattr(
        "ageval.plugins.contrib.docker.host.query_gpu_inventory",
        lambda: (),
    )
    host = DockerHost(
        spec=_spec(tmp_path / "box", tmp_path),
        options={"gpus": 1, "gpu_types": ["H100"]},
    )
    with pytest.raises(EnvironmentFailure) as caught:
        asyncio.run(host.start())
    assert caught.value.kind == "environment_gpu_unavailable"
    assert not any(call and call[0] == "run" for call in calls)


def test_start_pins_matching_gpu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []
    _patch_docker(monkeypatch, calls)
    monkeypatch.setattr(
        "ageval.plugins.contrib.docker.host.query_gpu_inventory",
        lambda: (GpuDevice(0, "NVIDIA H100 80GB HBM3"),),
    )
    host = DockerHost(
        spec=_spec(tmp_path / "box", tmp_path),
        options={"gpus": 1, "gpu_types": ["H100"], "cpus": 16, "memory_mb": 32768},
    )
    asyncio.run(_start_host(host))
    run = next(call for call in calls if call and call[0] == "run")
    assert run[run.index("--gpus") + 1] == "device=0"
    assert run[run.index("--cpus") + 1] == "16"
    assert run[run.index("--memory") + 1] == "32768m"


def test_compose_up_adds_deploy_resources_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compose = tmp_path / "environment" / "compose.yaml"
    compose.parent.mkdir(parents=True)
    compose.write_text(
        "services:\n  loadgen:\n    image: busybox\n    cpus: 1.0\n    mem_limit: 512m\n",
        encoding="utf-8",
    )
    calls: list[tuple[str, ...]] = []
    _patch_docker(monkeypatch, calls)
    host = DockerHost(
        spec=_spec(tmp_path / "box", tmp_path, compose_file="environment/compose.yaml"),
        options={"cpus": 2, "memory_mb": 4096},
    )

    async def _run() -> Path:
        await host.start()
        try:
            up = next(call for call in calls if call and call[0] == "compose" and "up" in call)
            files = [up[index + 1] for index, token in enumerate(up) if token == "-f"]
            assert len(files) == 2
            overlay = Path(files[1])
            text = overlay.read_text(encoding="utf-8")
            assert "cpus:" in text
            assert "memory:" in text
            assert "loadgen" in text
            return overlay
        finally:
            await host.stop(delete=True)

    overlay_path = asyncio.run(_run())
    assert not overlay_path.exists()


def _start(root: Path, options: dict[str, object]) -> tuple[str, ...]:
    calls: list[tuple[str, ...]] = []

    def fake_docker(*args: str, timeout: float = 600.0) -> subprocess.CompletedProcess[str]:
        del timeout
        calls.append(tuple(args))
        stdout = "cid\n" if args and args[0] == "run" else ""
        return subprocess.CompletedProcess(list(args), 0, stdout=stdout, stderr="")

    host = DockerHost(spec=_spec(root / "box", root), options=options)
    original_docker = __import__("ageval.plugins.contrib.docker.host", fromlist=["docker"])

    # Patch on the host module for this call only, then restore.
    previous_docker = original_docker.docker
    previous_resolve = original_docker.resolve_image
    original_docker.docker = fake_docker
    original_docker.resolve_image = lambda **_kwargs: ("img:test", "sha")
    try:
        asyncio.run(_start_host(host))
    finally:
        original_docker.docker = previous_docker
        original_docker.resolve_image = previous_resolve
    return next(call for call in calls if call and call[0] == "run")


def _patch_docker(monkeypatch: pytest.MonkeyPatch, calls: list[tuple[str, ...]]) -> None:
    def fake_docker(*args: str, timeout: float = 600.0) -> subprocess.CompletedProcess[str]:
        del timeout
        calls.append(tuple(args))
        stdout = "cid\n" if args and args[0] == "run" else ""
        return subprocess.CompletedProcess(list(args), 0, stdout=stdout, stderr="")

    monkeypatch.setattr("ageval.plugins.contrib.docker.host.docker", fake_docker)
    monkeypatch.setattr(
        "ageval.plugins.contrib.docker.host.resolve_image",
        lambda **_kwargs: ("img:test", "sha"),
    )


async def _start_host(host: DockerHost) -> None:
    await host.start()
    await host.stop(delete=True)


def _spec(attempt_root: Path, task_root: Path, compose_file: str | None = None) -> BoxSpec:
    return BoxSpec(
        attempt_root=attempt_root,
        task_root=task_root,
        repo_root=task_root,
        compose_file=compose_file,
    )


def _shape(argv: Sequence[str]) -> tuple[str, ...]:
    """Drop per-start names and bind paths so two unset runs can be compared."""
    skip = {"--name", "-v"}
    out: list[str] = []
    index = 0
    while index < len(argv):
        if argv[index] in skip:
            index += 2
            continue
        out.append(argv[index])
        index += 1
    return tuple(out)
