"""Rewrite a profiles file so a hosted job can only run on e2b or daytona."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from services.registry.hosted.rows import HOSTED_ENVIRONMENTS, JobRow

from ageval.application.agent_ops.resolve import bindings_from_agent_specs
from ageval.config.errors import ConfigError
from ageval.config.profiles import PROFILES_FORMAT, parse_job_mapping, write_profiles_yaml

_ENV_PLUGINS = frozenset({"docker", "local", "ssh", "podman", "e2b", "daytona"})


class HostedRunError(Exception):
    """A hosted job cannot start. ``code`` is stored on the job row."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PreparedRun:
    work_dir: Path
    dataset_root: Path
    profiles_path: Path
    environment: str
    model_locator: str
    model_value: str
    provider_locator: str
    provider_value: str
    max_concurrent_tasks: int
    task_id: str


def prepare_profiles(
    job: JobRow,
    dataset_root: Path,
    profiles_path: Path,
    *,
    model_locator: str,
    model_value: str,
    provider_locator: str,
    provider_value: str,
) -> PreparedRun:
    """Write ``profiles_path`` and refuse anything other than e2b or daytona."""
    if job.environment not in HOSTED_ENVIRONMENTS:
        raise HostedRunError(
            "hosted_environment_refused",
            "hosted jobs accept only e2b or daytona",
        )
    try:
        document = _source_document(job, dataset_root)
        _apply_job(document, job, model_locator)
        parse_job_mapping(document, location="hosted-profiles")
    except ConfigError as exc:
        raise HostedRunError(exc.error_code, exc.message) from exc
    write_profiles_yaml(profiles_path, document)
    text = profiles_path.read_text(encoding="utf-8")
    for secret in (model_value, provider_value):
        if secret and secret in text:
            raise HostedRunError(
                "hosted_secret_leak",
                "profiles file contains a secret value",
            )
    parsed = parse_job_mapping(
        yaml.safe_load(text),
        location=str(profiles_path),
    )
    if parsed.environment not in HOSTED_ENVIRONMENTS:
        raise HostedRunError(
            "hosted_environment_refused",
            "profiles environment is not e2b or daytona",
        )
    return PreparedRun(
        work_dir=profiles_path.parent,
        dataset_root=dataset_root,
        profiles_path=profiles_path,
        environment=parsed.environment,
        model_locator=model_locator,
        model_value=model_value,
        provider_locator=provider_locator,
        provider_value=provider_value,
        max_concurrent_tasks=job.max_concurrent_tasks,
        task_id=job.task_id,
    )


def _source_document(job: JobRow, dataset_root: Path) -> dict[str, Any]:
    if job.agent_ref.strip():
        bindings = bindings_from_agent_specs([job.agent_ref.strip()])
        return {
            "format": PROFILES_FORMAT,
            "environment": job.environment,
            "agent_profiles": bindings,
        }
    path = dataset_root / "profiles.yaml"
    if not path.is_file():
        raise HostedRunError("invalid_package", "dataset has no profiles.yaml")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise HostedRunError("invalid_package", f"invalid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise HostedRunError("invalid_package", "profiles.yaml root must be a mapping")
    return loaded


def _apply_job(document: dict[str, Any], job: JobRow, model_locator: str) -> None:
    document["format"] = PROFILES_FORMAT
    document["environment"] = job.environment
    profiles = document.get("agent_profiles")
    if not isinstance(profiles, dict):
        raise HostedRunError("invalid_package", "profiles.yaml requires agent_profiles")
    locator = "${" + model_locator + "}"
    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        profile["model"] = job.model
        profile["api_key"] = locator
        profile["extensions"] = _rewrite_extensions(profile.get("extensions"), job.environment)


def _rewrite_extensions(extensions: Any, environment: str) -> list[Any]:
    out: list[Any] = []
    placed = False
    items = extensions if isinstance(extensions, list) else []
    for item in items:
        if isinstance(item, dict) and str(item.get("plugin") or "") in _ENV_PLUGINS:
            if not placed:
                out.append({"plugin": environment})
                placed = True
            continue
        out.append(item)
    if not placed:
        out.append({"plugin": environment})
    return out
