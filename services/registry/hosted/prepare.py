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
from ageval.model.errors import ModelConfigError

_ENV_PLUGINS = frozenset({"docker", "local", "ssh", "podman", "e2b", "daytona"})
_FLAT_MODEL_KEYS = (
    "api",
    "reasoning_effort",
    "timeout",
    "request_timeout",
    "watchdog",
    "extra_body",
)


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
    except ModelConfigError as exc:
        raise HostedRunError(exc.kind, exc.message) from exc
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
        profile["model"] = _nested_model(profile.get("model"), str(job.model).strip())
        profile["api_key"] = locator
        _strip_flat_model_keys(profile)
        profile["extensions"] = _rewrite_extensions(profile.get("extensions"), job.environment)


def _nested_model(current: Any, model_id: str) -> dict[str, Any]:
    if isinstance(current, dict):
        updated = dict(current)
        updated["id"] = model_id
        return updated
    return {"id": model_id}


def _strip_flat_model_keys(profile: dict[str, Any]) -> None:
    options = profile.get("options")
    if isinstance(options, dict):
        for key in _FLAT_MODEL_KEYS:
            options.pop(key, None)
    rows = profile.get("extensions")
    if not isinstance(rows, list):
        return
    for item in rows:
        if not isinstance(item, dict):
            continue
        item_options = item.get("options")
        if not isinstance(item_options, dict):
            continue
        for key in _FLAT_MODEL_KEYS:
            item_options.pop(key, None)


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
