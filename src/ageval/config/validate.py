"""Document and package layout validation for Config Core."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ageval.config.capabilities import CapabilityCatalog
from ageval.config.constants import (
    ALLOWED_TOP_LEVEL_DIRS,
    ALLOWED_TOP_LEVEL_FILES,
    COMPOSE_DEFAULT,
    DOCKERFILE_DEFAULT,
    EVALUATE_DOCKERFILE_DEFAULT,
    EVALUATE_ENVIRONMENT_NAME_PATTERN,
    EVALUATION_DIR,
    EVALUATOR_ENTRYPOINT_DEFAULT,
    EVALUATOR_MODULE_FILE,
    REJECTED_TASK_KEYS,
    RUN_ENTRYPOINT_DEFAULT,
    RUN_MODULE_FILE,
    SEED_DIR,
    SETUP_SCRIPT_DEFAULT,
)
from ageval.config.digest import normalize_package_relpath
from ageval.config.errors import (
    ERROR_INVALID_FORMAT,
    ERROR_INVALID_PACKAGE,
    ERROR_INVALID_SCHEMA,
    ERROR_MISSING_REFERENCE,
    ERROR_PATH_OUTSIDE_PACKAGE,
    ERROR_UNKNOWN_PACKAGE_PATH,
    ERROR_UNKNOWN_PROFILE,
    ERROR_UNKNOWN_TASK,
    ERROR_UNSUPPORTED_CAPABILITY,
    ConfigError,
)
from ageval.config.ports import PackageReader
from ageval.environments.protocol import CAPABILITY_NAMES

ALLOWED_TASK_KEYS = frozenset(
    {
        "format",
        "task_id",
        "description",
        "parameters",
        "agent_profiles",
        "requires",
        "limits",
        "artifacts",
        "evaluation",
        "provenance",
    }
)

ALLOWED_LIMIT_KEYS = frozenset(
    {
        "wall_time_seconds",
        "environment_seconds",
        "evaluate_seconds",
        "agent_invocations",
    }
)
PUBLISHABLE_KEYS = frozenset({"id", "path", "kind", "exclude"})
PUBLISHABLE_KINDS = frozenset({"file", "tree"})
EVALUATION_KEYS = frozenset({"entrypoint", "inputs", "docker_image", "environments"})
EVALUATION_ENVIRONMENT_KEYS = frozenset({"dockerfile", "docker_image"})
_EVALUATE_ENVIRONMENT_NAME = re.compile(EVALUATE_ENVIRONMENT_NAME_PATTERN)


def validate_top_level_layout(reader: PackageReader, root: Path) -> None:
    try:
        names = reader.list_top_level(root)
    except OSError as exc:
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            f"cannot list package root: {exc}",
            location=str(root),
        ) from exc

    for name in names:
        if name.startswith(".") or name == "__pycache__":
            continue
        path = root / name
        if path.is_dir():
            if name not in ALLOWED_TOP_LEVEL_DIRS:
                raise ConfigError(
                    ERROR_UNKNOWN_PACKAGE_PATH,
                    f"unknown top-level directory: {name}",
                    location=name,
                )
        elif name not in ALLOWED_TOP_LEVEL_FILES:
            raise ConfigError(
                ERROR_UNKNOWN_PACKAGE_PATH,
                f"unknown top-level file: {name}",
                location=name,
            )


def validate_document(
    reader: PackageReader,
    doc: dict[str, Any],
    *,
    task_id: str,
    root: Path,
    capabilities: CapabilityCatalog,
) -> None:
    """Validate a merged ``ageval.task/1`` document against the package on disk."""
    _reject_retired_keys(doc)

    fmt = doc.get("format")
    if not isinstance(fmt, str) or not fmt:
        raise ConfigError(ERROR_INVALID_FORMAT, "missing or invalid format", location="/format")
    if not capabilities.supports_format(fmt):
        raise ConfigError(
            ERROR_INVALID_FORMAT,
            f"unsupported format: {fmt}",
            location="/format",
        )

    unknown = sorted(set(doc) - ALLOWED_TASK_KEYS)
    if unknown:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"unknown task keys: {unknown}",
            location="/",
        )

    yaml_task = doc.get("task_id")
    if not isinstance(yaml_task, str) or not yaml_task:
        raise ConfigError(ERROR_INVALID_SCHEMA, "missing task_id", location="/task_id")
    if yaml_task != task_id:
        raise ConfigError(
            ERROR_UNKNOWN_TASK,
            f"task_id mismatch: cli={task_id!r} yaml={yaml_task!r}",
            location="/task_id",
        )

    if not reader.exists(root, RUN_MODULE_FILE):
        raise ConfigError(
            ERROR_MISSING_REFERENCE,
            f"{RUN_MODULE_FILE} not found (a task must ship its run phase entry)",
            location=RUN_MODULE_FILE,
        )
    if not reader.exists(root, EVALUATOR_MODULE_FILE):
        raise ConfigError(
            ERROR_MISSING_REFERENCE,
            f"{EVALUATOR_MODULE_FILE} not found (PASS may only come from an evaluator)",
            location=EVALUATOR_MODULE_FILE,
        )

    parameters = doc.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ConfigError(
            ERROR_INVALID_SCHEMA, "parameters must be a mapping", location="/parameters"
        )
    assert_json_compatible(parameters, "/parameters")

    profile_ids = _validate_profiles(doc, capabilities=capabilities)
    _validate_parameter_model_refs(parameters, profile_ids)
    _validate_requires(doc.get("requires"))
    _validate_limits(doc.get("limits"))
    artifact_ids = _validate_artifacts(doc.get("artifacts"))
    _validate_evaluation(
        doc.get("evaluation"),
        artifact_ids=artifact_ids,
        reader=reader,
        root=root,
    )


def _reject_retired_keys(doc: dict[str, Any]) -> None:
    for key, hint in REJECTED_TASK_KEYS.items():
        if key in doc:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                f"task.yaml key {key!r} is not part of ageval.task/1: {hint}",
                location=f"/{key}",
            )


def _validate_profiles(
    doc: dict[str, Any],
    *,
    capabilities: CapabilityCatalog,
) -> set[str]:
    from ageval.config.checks import require_agent_profiles_list

    profiles = require_agent_profiles_list(doc.get("agent_profiles") or [])
    profile_ids: set[str] = set()
    for idx, profile in enumerate(profiles):
        loc = f"/agent_profiles/{idx}"
        if not isinstance(profile, dict):
            raise ConfigError(ERROR_INVALID_SCHEMA, "profile must be a mapping", location=loc)
        pid = profile.get("id")
        if not isinstance(pid, str) or not pid:
            raise ConfigError(ERROR_INVALID_SCHEMA, "profile.id required", location=f"{loc}/id")
        if pid in profile_ids:
            raise ConfigError(
                ERROR_INVALID_SCHEMA, f"duplicate profile id: {pid}", location=f"{loc}/id"
            )
        profile_ids.add(pid)
        executor = profile.get("executor")
        if not isinstance(executor, str) or not executor.strip():
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "profile.executor required (bound from the job document)",
                location=f"{loc}/executor",
            )
        if executor == "acp":
            _validate_acp_profile(profile, loc=loc, capabilities=capabilities)
        _validate_routing(profile, loc=loc)
    return profile_ids


def _validate_acp_profile(
    profile: dict[str, Any],
    *,
    loc: str,
    capabilities: CapabilityCatalog,
) -> None:
    """``executor: acp`` needs a known ``options.entry`` and no recipe overrides."""
    from ageval.config.profiles import plugin_row_options

    options = plugin_row_options(profile, "acp")
    entry = options.get("entry")
    if not isinstance(entry, str) or not entry.strip():
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "executor acp requires options.entry",
            location=f"{loc}/options/entry",
        )
    for forbidden in (
        "command",
        "args",
        "detect_command",
        "install_command",
        "version",
        "acp_command",
        "engine_command",
        "acp_version",
        "credential_env_names",
    ):
        if forbidden in options:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                f"options.{forbidden} belongs to the entry registry, not the job",
                location=f"{loc}/options/{forbidden}",
            )
    if not capabilities.supports_acp_entry(entry.strip()):
        raise ConfigError(
            ERROR_UNSUPPORTED_CAPABILITY,
            f"unknown acp entry: {entry!r}",
            location=f"{loc}/options/entry",
        )


def _validate_routing(profile: dict[str, Any], *, loc: str) -> None:
    """``base_url`` is a locator name or http(s) URL; ``api_key`` is a locator."""
    from ageval.config.env_refs import is_http_url, is_locator_name

    base_url = profile.get("base_url")
    if base_url is not None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "profile.base_url must be a non-empty string when set",
                location=f"{loc}/base_url",
            )
        if not is_http_url(base_url) and not is_locator_name(base_url):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "profile.base_url must be ${ENV_NAME} or an http(s) URL",
                location=f"{loc}/base_url",
            )
    api_key = profile.get("api_key")
    if api_key is None:
        return
    if not isinstance(api_key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "profile.api_key must be an environment variable name (locator only)",
            location=f"{loc}/api_key",
        )
    if api_key.startswith("sk-") or len(api_key) > 64:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "profile.api_key looks like a secret value; use the env var name only",
            location=f"{loc}/api_key",
        )


def _validate_parameter_model_refs(parameters: dict[str, Any], profile_ids: set[str]) -> None:
    """``parameters.active_profile`` must name a role slot the task declared."""
    active = parameters.get("active_profile")
    if active is None:
        return
    if not isinstance(active, str) or not active.strip():
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "parameters.active_profile must be a role slot id",
            location="/parameters/active_profile",
        )
    if active.strip() not in profile_ids:
        raise ConfigError(
            ERROR_UNKNOWN_PROFILE,
            f"unknown agent profile reference: {active.strip()}",
            location="/parameters/active_profile",
        )


def _validate_requires(requires: Any) -> None:
    """``requires.environment`` names capabilities the box must deliver."""
    if requires is None:
        return
    if not isinstance(requires, dict):
        raise ConfigError(ERROR_INVALID_SCHEMA, "requires must be a mapping", location="/requires")
    unknown = sorted(set(requires) - {"environment"})
    if unknown:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"unknown requires keys: {unknown}",
            location="/requires",
        )
    caps = requires.get("environment") or []
    if not isinstance(caps, list):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "requires.environment must be a list of capability names",
            location="/requires/environment",
        )
    bad = sorted({str(c) for c in caps} - CAPABILITY_NAMES)
    if bad:
        raise ConfigError(
            ERROR_UNSUPPORTED_CAPABILITY,
            f"unknown environment capabilities: {bad} (known: {sorted(CAPABILITY_NAMES)})",
            location="/requires/environment",
        )


def _validate_limits(limits: Any) -> None:
    if not isinstance(limits, dict):
        raise ConfigError(ERROR_INVALID_SCHEMA, "limits must be a mapping", location="/limits")
    unknown = sorted(set(limits) - ALLOWED_LIMIT_KEYS)
    if unknown:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"unknown limits keys: {unknown} (known: {sorted(ALLOWED_LIMIT_KEYS)})",
            location="/limits",
        )
    for key in sorted(ALLOWED_LIMIT_KEYS):
        if key not in limits:
            continue
        val = limits[key]
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                f"limits.{key} must be a non-negative integer",
                location=f"/limits/{key}",
            )


def _validate_artifacts(artifacts: Any) -> set[str]:
    if not isinstance(artifacts, dict):
        raise ConfigError(
            ERROR_INVALID_SCHEMA, "artifacts must be a mapping", location="/artifacts"
        )
    publishable = artifacts.get("publishable", [])
    if not isinstance(publishable, list):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "artifacts.publishable must be a list",
            location="/artifacts/publishable",
        )
    artifact_ids: set[str] = set()
    for idx, item in enumerate(publishable):
        loc = f"/artifacts/publishable/{idx}"
        if not isinstance(item, dict):
            raise ConfigError(
                ERROR_INVALID_SCHEMA, "artifact entry must be a mapping", location=loc
            )
        unknown = sorted(set(item) - PUBLISHABLE_KEYS)
        if unknown:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                f"unknown artifacts.publishable keys: {unknown}",
                location=loc,
            )
        aid = item.get("id")
        if not isinstance(aid, str) or not aid:
            raise ConfigError(ERROR_INVALID_SCHEMA, "artifact.id required", location=f"{loc}/id")
        artifact_ids.add(aid)
        path = item.get("path")
        if not isinstance(path, str) or not path:
            raise ConfigError(
                ERROR_INVALID_SCHEMA, "artifact.path required", location=f"{loc}/path"
            )
        normalize_package_relpath(path)
        kind = item.get("kind")
        if kind is None:
            kind = "file"
        elif not isinstance(kind, str) or kind not in PUBLISHABLE_KINDS:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "artifact.kind must be file or tree",
                location=f"{loc}/kind",
            )
        exclude = item.get("exclude")
        if exclude is None:
            continue
        if kind != "tree":
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "artifact.exclude is only valid with kind: tree",
                location=f"{loc}/exclude",
            )
        if not isinstance(exclude, list) or not all(
            isinstance(part, str) and part.strip() for part in exclude
        ):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "artifact.exclude must be a list of non-empty strings",
                location=f"{loc}/exclude",
            )
    return artifact_ids


def _validate_evaluation(
    evaluation: Any,
    *,
    artifact_ids: set[str],
    reader: PackageReader,
    root: Path,
) -> None:
    if not isinstance(evaluation, dict):
        raise ConfigError(
            ERROR_INVALID_SCHEMA, "evaluation must be a mapping", location="/evaluation"
        )
    unknown = sorted(set(evaluation) - EVALUATION_KEYS)
    if unknown:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"unknown evaluation keys: {unknown}",
            location="/evaluation",
        )
    docker_image = evaluation.get("docker_image")
    if docker_image is not None and (not isinstance(docker_image, str) or not docker_image.strip()):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "evaluation.docker_image must be a non-empty image tag",
            location="/evaluation/docker_image",
        )
    entrypoint = evaluation.get("entrypoint")
    if entrypoint is not None and (not isinstance(entrypoint, str) or ":" not in entrypoint):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "evaluation.entrypoint must be module:function",
            location="/evaluation/entrypoint",
        )
    inputs = evaluation.get("inputs", [])
    if not isinstance(inputs, list):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "evaluation.inputs must be a list",
            location="/evaluation/inputs",
        )
    for idx, inp in enumerate(inputs):
        loc = f"/evaluation/inputs/{idx}"
        if not isinstance(inp, dict):
            raise ConfigError(
                ERROR_INVALID_SCHEMA, "evaluation input must be a mapping", location=loc
            )
        unknown_input = sorted(set(inp) - {"artifact", "package_path", "target"})
        if unknown_input:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                f"unknown evaluation input keys: {unknown_input}",
                location=loc,
            )
        if "artifact" in inp and inp["artifact"] not in artifact_ids:
            raise ConfigError(
                ERROR_MISSING_REFERENCE,
                f"evaluation input references unknown artifact: {inp['artifact']}",
                location=loc,
            )
        if "package_path" in inp:
            pp = inp["package_path"]
            if not isinstance(pp, str):
                raise ConfigError(
                    ERROR_INVALID_SCHEMA, "package_path must be a string", location=loc
                )
            rel = normalize_package_relpath(pp)
            if ".." in Path(rel).parts:
                raise ConfigError(
                    ERROR_PATH_OUTSIDE_PACKAGE, f"path escapes package: {pp}", location=loc
                )
    if "environments" in evaluation:
        _validate_evaluation_environments(
            evaluation.get("environments"),
            reader=reader,
            root=root,
        )


def _validate_evaluation_environments(
    environments: Any,
    *,
    reader: PackageReader,
    root: Path,
) -> None:
    if not isinstance(environments, dict):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "evaluation.environments must be a mapping",
            location="/evaluation/environments",
        )
    if not environments:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "evaluation.environments must not be empty",
            location="/evaluation/environments",
        )
    for name, recipe in environments.items():
        loc = f"/evaluation/environments/{name}"
        if not isinstance(name, str) or not _EVALUATE_ENVIRONMENT_NAME.fullmatch(name):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "evaluation environment name must match [a-z][a-z0-9_-]*",
                location=loc,
            )
        if not isinstance(recipe, dict):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "evaluation environment recipe must be a mapping",
                location=loc,
            )
        unknown = sorted(set(recipe) - EVALUATION_ENVIRONMENT_KEYS)
        if unknown:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                f"unknown evaluation environment keys: {unknown}",
                location=loc,
            )
        dockerfile = recipe.get("dockerfile")
        docker_image = recipe.get("docker_image")
        if dockerfile is None and docker_image is None:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "evaluation environment requires dockerfile or docker_image",
                location=loc,
            )
        if docker_image is not None and (
            not isinstance(docker_image, str) or not docker_image.strip()
        ):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "evaluation environment docker_image must be a non-empty image tag",
                location=f"{loc}/docker_image",
            )
        if dockerfile is None:
            continue
        if not isinstance(dockerfile, str) or not dockerfile.strip():
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "evaluation environment dockerfile must be a non-empty path",
                location=f"{loc}/dockerfile",
            )
        rel = normalize_package_relpath(dockerfile)
        if Path(rel).parts[:1] == ("evaluation",):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "evaluation environment dockerfile must not live under evaluation/",
                location=f"{loc}/dockerfile",
            )
        if not reader.exists(root, rel):
            raise ConfigError(
                ERROR_MISSING_REFERENCE,
                f"evaluation environment dockerfile missing: {rel}",
                location=f"{loc}/dockerfile",
            )


def collect_resolved_references(
    reader: PackageReader,
    doc: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    """Resolve the file-based defaults: what the task ships is what runs."""
    evaluation = doc.get("evaluation") or {}
    refs: dict[str, Any] = {
        "run_entrypoint": RUN_ENTRYPOINT_DEFAULT,
        "run_module_file": RUN_MODULE_FILE,
        "evaluation_entrypoint": str(evaluation.get("entrypoint") or EVALUATOR_ENTRYPOINT_DEFAULT),
        "evaluation_module_file": EVALUATOR_MODULE_FILE,
        "artifacts": [],
        "evaluation_inputs": [],
    }
    if reader.exists(root, DOCKERFILE_DEFAULT):
        refs["environment_dockerfile"] = DOCKERFILE_DEFAULT
    if reader.exists(root, EVALUATE_DOCKERFILE_DEFAULT):
        refs["environment_evaluate_dockerfile"] = EVALUATE_DOCKERFILE_DEFAULT
    if reader.exists(root, COMPOSE_DEFAULT):
        refs["environment_compose"] = COMPOSE_DEFAULT
    if reader.exists(root, SETUP_SCRIPT_DEFAULT):
        refs["environment_setup"] = SETUP_SCRIPT_DEFAULT
    if reader.exists(root, SEED_DIR):
        refs["seed_dir"] = SEED_DIR
    if reader.exists(root, EVALUATION_DIR):
        refs["evaluation_dir"] = EVALUATION_DIR
    eval_image = evaluation.get("docker_image")
    if isinstance(eval_image, str) and eval_image.strip():
        refs["evaluation_docker_image"] = eval_image.strip()
    named = evaluation.get("environments")
    if isinstance(named, dict) and named:
        refs["evaluation_environments"] = _collect_evaluation_environments(named)
    for item in (doc.get("artifacts") or {}).get("publishable") or []:
        if isinstance(item, dict):
            row: dict[str, Any] = {
                "id": item.get("id"),
                "path": normalize_package_relpath(str(item.get("path", ""))),
            }
            kind = item.get("kind")
            if isinstance(kind, str) and kind.strip() and kind != "file":
                row["kind"] = kind.strip()
            exclude = item.get("exclude")
            if isinstance(exclude, list) and exclude:
                row["exclude"] = [str(part) for part in exclude]
            refs["artifacts"].append(row)
    for inp in evaluation.get("inputs") or []:
        if not isinstance(inp, dict):
            continue
        entry: dict[str, Any] = {}
        if "artifact" in inp:
            entry["artifact"] = inp["artifact"]
        if "package_path" in inp:
            entry["package_path"] = normalize_package_relpath(str(inp["package_path"]))
        if "target" in inp:
            entry["target"] = str(inp["target"])
        refs["evaluation_inputs"].append(entry)
    return refs


def _collect_evaluation_environments(named: dict[str, Any]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for name, recipe in named.items():
        if not isinstance(name, str) or not isinstance(recipe, dict):
            continue
        entry: dict[str, str] = {}
        dockerfile = recipe.get("dockerfile")
        if isinstance(dockerfile, str) and dockerfile.strip():
            entry["dockerfile"] = normalize_package_relpath(dockerfile)
        docker_image = recipe.get("docker_image")
        if isinstance(docker_image, str) and docker_image.strip():
            entry["docker_image"] = docker_image.strip()
        if entry:
            out[name] = entry
    return out


def assert_json_compatible(value: Any, location: str) -> None:
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            assert_json_compatible(item, f"{location}/{i}")
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ConfigError(
                    ERROR_INVALID_SCHEMA,
                    "mapping keys must be strings",
                    location=location,
                )
            assert_json_compatible(v, f"{location}/{k}")
        return
    raise ConfigError(
        ERROR_INVALID_SCHEMA,
        f"unsupported value type: {type(value).__name__}",
        location=location,
    )
