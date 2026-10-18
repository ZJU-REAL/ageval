"""Lock rejects a bad resource parameter and docker options come from the lock."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from tests.helpers.lock import job_document, lock_standalone

from ageval.application.run import _agent_environment_options
from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.phases.evaluate import _scoring_environment_options
from ageval.config.errors import ConfigError
from ageval.config.model import thaw
from ageval.config.resources import parse_task_resources, resource_options
from ageval.plugins.protocol import ExtensionGraph

LOCAL = {
    "executor": "acp",
    "model": {"id": "entry-default"},
    "options": {"entry": "codex"},
    "extensions": [{"plugin": "acp"}, {"plugin": "local"}],
}
DOCKER = {
    "executor": "acp",
    "model": {"id": "entry-default"},
    "options": {"entry": "codex"},
    "extensions": [{"plugin": "acp"}, {"plugin": "docker"}],
}


def test_zero_gpu_parameters_leave_cpu_and_memory_only() -> None:
    parameters = {
        "cpus": 2,
        "memory_mb": 4096,
        "gpus": 0,
        "gpu_types": [],
        "verifier_gpus": 0,
    }
    parsed = parse_task_resources(parameters)
    assert parsed.cpus == 2
    assert parsed.memory_mb == 4096
    assert parsed.gpus == 0
    assert parsed.gpu_types == ()
    assert resource_options(parameters, scoring=False) == {"cpus": 2, "memory_mb": 4096}
    assert resource_options(parameters, scoring=True) == {}


def test_gpu_types_without_a_count_request_one_gpu() -> None:
    options = resource_options({"gpus": 0, "gpu_types": ["H100"]}, scoring=False)
    assert options == {"gpus": 1, "gpu_types": ["H100"]}


def test_verifier_gpus_apply_only_to_the_scoring_box() -> None:
    parameters = {
        "cpus": 16,
        "memory_mb": 32768,
        "gpus": 1,
        "gpu_types": ["H100"],
        "verifier_gpus": 1,
    }
    assert resource_options(parameters, scoring=True) == {"gpus": 1, "gpu_types": ["H100"]}
    assert "cpus" not in resource_options(parameters, scoring=True)


@pytest.mark.parametrize(
    ("parameters", "pointer"),
    [
        ({"gpus": True}, "/parameters/gpus"),
        ({"cpus": -1}, "/parameters/cpus"),
        ({"memory_mb": "4096"}, "/parameters/memory_mb"),
        ({"gpu_types": "H100"}, "/parameters/gpu_types"),
        ({"verifier_gpus": 1.5}, "/parameters/verifier_gpus"),
    ],
)
def test_bad_resource_parameters_fail_lock(
    tmp_path: Path, parameters: dict[str, Any], pointer: str
) -> None:
    root = _task(tmp_path, parameters)
    with pytest.raises(ConfigError) as caught:
        lock_standalone(root, "boxed", job=job_document({"solver": dict(LOCAL)}))
    assert caught.value.error_code == "invalid_schema"
    assert caught.value.location == pointer


def test_docker_lock_projects_agent_and_scoring_options(tmp_path: Path) -> None:
    root = _task(
        tmp_path,
        {
            "cpus": 2,
            "memory_mb": 4096,
            "gpus": 1,
            "gpu_types": ["H100"],
            "verifier_gpus": 1,
        },
    )
    locked = lock_standalone(
        root,
        "boxed",
        job=job_document({"solver": dict(DOCKER)}, environment="docker"),
    )
    assert thaw(locked.parameters)["gpus"] == 1
    agent = _agent_environment_options(locked, ExtensionGraph(profile_id="solver"))
    assert agent["cpus"] == 2
    assert agent["memory_mb"] == 4096
    assert agent["gpus"] == 1
    assert agent["gpu_types"] == ["H100"]
    scoring = _scoring_environment_options(cast(AttemptCtx, SimpleNamespace(lock=locked)))
    assert scoring["gpus"] == 1
    assert scoring["gpu_types"] == ["H100"]
    assert "cpus" not in scoring
    assert "memory_mb" not in scoring


def test_local_lock_does_not_project_docker_limits(tmp_path: Path) -> None:
    root = _task(tmp_path, {"cpus": 2, "memory_mb": 4096, "gpus": 1})
    locked = lock_standalone(root, "boxed", job=job_document({"solver": dict(LOCAL)}))
    options = _agent_environment_options(locked, ExtensionGraph(profile_id="solver"))
    assert "cpus" not in options
    assert "gpus" not in options


def _task(root: Path, parameters: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    lines = ["format: ageval.task/1", "task_id: boxed", "parameters:"]
    for key, value in parameters.items():
        if isinstance(value, list):
            lines.append(f"  {key}:")
            lines.extend(f"    - {item}" for item in value)
        elif isinstance(value, str):
            lines.append(f"  {key}: {value!r}")
        elif isinstance(value, bool):
            lines.append(f"  {key}: {'true' if value else 'false'}")
        else:
            lines.append(f"  {key}: {value}")
    lines.extend(
        [
            "agent_profiles:",
            "  - id: solver",
            "artifacts:",
            "  publishable: []",
            "evaluation:",
            "  inputs: []",
        ]
    )
    (root / "task.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "run.py").write_text("#\n", encoding="utf-8")
    (root / "evaluator.py").write_text("#\n", encoding="utf-8")
    return root
