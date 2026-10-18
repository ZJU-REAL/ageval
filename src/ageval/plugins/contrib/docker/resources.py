"""docker run flags and the compose resource override for one box.

``gpus: 0`` and an empty ``gpu_types`` add nothing. A required GPU is resolved
before any container starts: a miss is ``environment_gpu_unavailable``.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from ageval.environments.protocol import EnvironmentFailure


@dataclass(frozen=True, slots=True)
class GpuDevice:
    """One GPU ``nvidia-smi`` listed."""

    index: int
    name: str


@dataclass(frozen=True, slots=True)
class DockerRunResources:
    """Limits to put on this container. Unset fields add no flag."""

    cpus: float | None = None
    memory_mb: int | None = None
    gpus: int = 0
    gpu_types: tuple[str, ...] = ()


def resources_from_options(options: Mapping[str, object]) -> DockerRunResources:
    """Read the four option keys the application copies from task parameters."""
    cpus = _cpus(options.get("cpus")) if "cpus" in options else None
    memory_mb = _memory(options.get("memory_mb")) if "memory_mb" in options else None
    gpus = _count(options.get("gpus"), label="gpus") if "gpus" in options else 0
    gpu_types = _types(options.get("gpu_types")) if "gpu_types" in options else ()
    if gpu_types and gpus == 0:
        gpus = 1
    return DockerRunResources(
        cpus=cpus,
        memory_mb=memory_mb,
        gpus=gpus,
        gpu_types=gpu_types,
    )


def docker_run_resource_args(
    resources: DockerRunResources,
    inventory: Sequence[GpuDevice],
) -> list[str]:
    """``docker run`` flags. Raises when a required GPU is not in *inventory*."""
    args: list[str] = []
    if resources.cpus is not None:
        args.extend(["--cpus", _cpu_token(resources.cpus)])
    if resources.memory_mb is not None:
        args.extend(["--memory", f"{resources.memory_mb}m"])
    if resources.gpus <= 0:
        return args
    chosen = _select_gpus(inventory, count=resources.gpus, types=resources.gpu_types)
    if resources.gpu_types:
        indexes = ",".join(str(device.index) for device in chosen)
        args.extend(["--gpus", f"device={indexes}"])
    else:
        args.extend(["--gpus", f"count={resources.gpus}"])
    return args


def query_gpu_inventory() -> tuple[GpuDevice, ...]:
    """GPUs visible to ``nvidia-smi``. A missing or failed probe is unavailable."""
    try:
        completed = subprocess.run(  # noqa: S603 — fixed nvidia-smi query, no shell
            ["nvidia-smi", "--query-gpu=index,name", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise EnvironmentFailure(
            "environment_gpu_unavailable",
            "nvidia-smi is not available on this docker host",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise EnvironmentFailure(
            "environment_gpu_unavailable",
            "nvidia-smi did not answer on this docker host",
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-300:]
        raise EnvironmentFailure(
            "environment_gpu_unavailable",
            f"nvidia-smi failed on this docker host: {detail}",
        )
    return parse_gpu_inventory(completed.stdout or "")


def parse_gpu_inventory(text: str) -> tuple[GpuDevice, ...]:
    """Parse ``nvidia-smi --query-gpu=index,name --format=csv,noheader``."""
    devices: list[GpuDevice] = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        index_text, _, name = raw.partition(",")
        index_text = index_text.strip()
        name = name.strip()
        if not index_text.isdigit() or not name:
            continue
        devices.append(GpuDevice(index=int(index_text), name=name))
    return tuple(devices)


# deploy.resources.limits copied from a sidecar's own cpus / mem_limit.
_ServiceOverlay = dict[str, dict[str, dict[str, dict[str, str]]]]


def sidecar_resource_overlay(document: object) -> dict[str, dict[str, _ServiceOverlay]] | None:
    """Copy a sidecar's own ``cpus`` / ``mem_limit`` into ``deploy.resources.limits``.

    Services that already set ``deploy.resources.limits``, and services that
    declare no limit, are left alone. The agent's CPU, memory, and GPU are not
    copied onto sidecars.
    """
    if document is None:
        return None
    if not isinstance(document, dict):
        raise EnvironmentFailure(
            "environment_compose_failed",
            "compose file must be a mapping to apply sidecar resource limits",
        )
    services = document.get("services")
    if services is None:
        return None
    if not isinstance(services, dict):
        raise EnvironmentFailure(
            "environment_compose_failed",
            "compose services must be a mapping to apply sidecar resource limits",
        )
    overlay_services: dict[str, _ServiceOverlay] = {}
    for name, service in services.items():
        if not isinstance(name, str) or not isinstance(service, dict):
            continue
        limits = _sidecar_limits(service)
        if limits is None:
            continue
        overlay_services[name] = {"deploy": {"resources": {"limits": limits}}}
    if not overlay_services:
        return None
    return {"services": overlay_services}


def write_sidecar_overlay(compose_path: Path) -> Path | None:
    """Write the override next to nowhere in the task tree. ``None`` when unneeded."""
    try:
        document = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise EnvironmentFailure(
            "environment_compose_failed",
            f"cannot read compose resources: {exc}",
        ) from exc
    overlay = sidecar_resource_overlay(document)
    if overlay is None:
        return None
    with tempfile.NamedTemporaryFile(
        prefix="ageval-compose-resources-",
        suffix=".yml",
        delete=False,
        mode="w",
        encoding="utf-8",
    ) as handle:
        yaml.safe_dump(overlay, handle, sort_keys=False)
        return Path(handle.name)


def _select_gpus(
    inventory: Sequence[GpuDevice],
    *,
    count: int,
    types: tuple[str, ...],
) -> tuple[GpuDevice, ...]:
    pool = list(inventory)
    if types:
        wanted = tuple(token.casefold() for token in types)
        pool = [
            device for device in pool if any(token in device.name.casefold() for token in wanted)
        ]
    if len(pool) < count:
        visible = ", ".join(device.name for device in inventory) or "none"
        if types:
            need = f"need {count} GPU(s) matching {', '.join(types)}"
        else:
            need = f"need {count} GPU(s)"
        raise EnvironmentFailure(
            "environment_gpu_unavailable",
            f"docker host cannot provide the required GPU ({need}; visible: {visible})",
        )
    return tuple(pool[:count])


def _sidecar_limits(service: Mapping[str, object]) -> dict[str, str] | None:
    deploy = service.get("deploy")
    if isinstance(deploy, dict):
        resources = deploy.get("resources")
        if isinstance(resources, dict) and isinstance(resources.get("limits"), dict):
            return None
    limits: dict[str, str] = {}
    cpus = _limit_token(service.get("cpus"))
    if cpus is not None:
        limits["cpus"] = cpus
    memory = service.get("mem_limit")
    memory_token = _memory_token(memory)
    if memory_token is not None:
        limits["memory"] = memory_token
    return limits or None


def _limit_token(raw: object) -> str | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        if raw <= 0:
            return None
        return _cpu_token(float(raw))
    if isinstance(raw, str) and raw.strip() and raw.strip() not in {"0", "0.0"}:
        return raw.strip()
    return None


def _memory_token(raw: object) -> str | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        if raw <= 0:
            return None
        return str(int(raw)) if float(raw) == int(raw) else str(raw)
    if isinstance(raw, str) and raw.strip() and raw.strip() not in {"0", "0.0"}:
        return raw.strip()
    return None


def _cpu_token(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return format(value, "g")


def _cpus(raw: object) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 0:
        raise EnvironmentFailure(
            "environment_options_invalid",
            f"docker resource cpus must be a non-negative number, got {raw!r}",
        )
    if raw == 0:
        return None
    return float(raw)


def _memory(raw: object) -> int | None:
    count = _count(raw, label="memory_mb")
    return None if count == 0 else count


def _count(raw: object, *, label: str) -> int:
    if raw is None:
        return 0
    if isinstance(raw, bool):
        raise EnvironmentFailure(
            "environment_options_invalid",
            f"docker resource {label} must be a non-negative integer, got {raw!r}",
        )
    if isinstance(raw, float):
        if raw >= 0 and raw == int(raw):
            return int(raw)
        raise EnvironmentFailure(
            "environment_options_invalid",
            f"docker resource {label} must be a non-negative integer, got {raw!r}",
        )
    if isinstance(raw, int) and raw >= 0:
        return raw
    raise EnvironmentFailure(
        "environment_options_invalid",
        f"docker resource {label} must be a non-negative integer, got {raw!r}",
    )


def _types(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise EnvironmentFailure(
            "environment_options_invalid",
            f"docker resource gpu_types must be a list of strings, got {raw!r}",
        )
    types: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise EnvironmentFailure(
                "environment_options_invalid",
                f"docker resource gpu_types must be a list of strings, got {raw!r}",
            )
        types.append(item.strip())
    return tuple(types)
