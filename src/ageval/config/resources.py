"""Task parameters that the docker kind enforces as container limits.

The keys stay on ``parameters`` (and therefore on ``ctx.params``). Lock rejects
a bad shape. The docker plugin reads the normalized options the application
copies out of here. Residual task.toml is not a source.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError


@dataclass(frozen=True, slots=True)
class TaskResources:
    """Normalized resource parameters. ``None`` / ``0`` / empty means unset."""

    cpus: int | float | None = None
    memory_mb: int | None = None
    gpus: int = 0
    gpu_types: tuple[str, ...] = ()
    verifier_gpus: int = 0


def parse_task_resources(parameters: Mapping[str, Any]) -> TaskResources:
    """Read the resource keys. Absent keys are unset. A present bad value fails."""
    return TaskResources(
        cpus=_cpus(parameters.get("cpus")) if "cpus" in parameters else None,
        memory_mb=_memory(parameters.get("memory_mb")) if "memory_mb" in parameters else None,
        gpus=_count(parameters.get("gpus"), key="gpus") if "gpus" in parameters else 0,
        gpu_types=_gpu_types(parameters.get("gpu_types")) if "gpu_types" in parameters else (),
        verifier_gpus=_count(parameters.get("verifier_gpus"), key="verifier_gpus")
        if "verifier_gpus" in parameters
        else 0,
    )


def resource_options(parameters: Mapping[str, Any], *, scoring: bool) -> dict[str, Any]:
    """Options the docker host understands. Empty when this box has no limit to apply."""
    parsed = parse_task_resources(parameters)
    if scoring:
        if parsed.verifier_gpus <= 0:
            return {}
        options: dict[str, Any] = {"gpus": parsed.verifier_gpus}
        if parsed.gpu_types:
            options["gpu_types"] = list(parsed.gpu_types)
        return options
    options = {}
    if parsed.cpus is not None:
        options["cpus"] = parsed.cpus
    if parsed.memory_mb is not None:
        options["memory_mb"] = parsed.memory_mb
    gpus = parsed.gpus
    if parsed.gpu_types and gpus == 0:
        gpus = 1
    if gpus > 0:
        options["gpus"] = gpus
    if parsed.gpu_types:
        options["gpu_types"] = list(parsed.gpu_types)
    return options


def _cpus(raw: object) -> int | float | None:
    number = _non_negative_number(raw, key="cpus")
    if number == 0:
        return None
    if number == int(number):
        return int(number)
    return number


def _memory(raw: object) -> int | None:
    count = _count(raw, key="memory_mb")
    return None if count == 0 else count


def _count(raw: object, *, key: str) -> int:
    if isinstance(raw, bool):
        raise _bad(key)
    if isinstance(raw, float):
        if math.isfinite(raw) and raw >= 0 and raw == int(raw):
            return int(raw)
        raise _bad(key)
    if isinstance(raw, int) and raw >= 0:
        return raw
    raise _bad(key)


def _non_negative_number(raw: object, *, key: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _bad(key)
    if isinstance(raw, float) and not math.isfinite(raw):
        raise _bad(key)
    if raw < 0:
        raise _bad(key)
    return float(raw)


def _gpu_types(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise _bad("gpu_types")
    types: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise _bad("gpu_types")
        types.append(item.strip())
    return tuple(types)


def _bad(key: str) -> ConfigError:
    if key == "cpus":
        message = "parameters.cpus must be a non-negative number"
    elif key == "gpu_types":
        message = "parameters.gpu_types must be a list of non-empty strings"
    else:
        message = f"parameters.{key} must be a non-negative integer"
    return ConfigError(ERROR_INVALID_SCHEMA, message, location=f"/parameters/{key}")
