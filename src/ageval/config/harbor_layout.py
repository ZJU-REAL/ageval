"""Explicit Harbor task and task-set intake (``--layout harbor``).

The flag is required. Nothing here sniffs a tree and decides it is Harbor.
A Harbor tree never needs ``ageval.yaml``, ``task.yaml``, ``run.py``, or
``evaluator.py``. Lock synthesizes an ``ageval.task/1`` document and points
the run and evaluate entrypoints at ``ageval.harbor``.
"""

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ageval.config.constants import DEFAULTS
from ageval.config.dataset import (
    DATASET_FORMAT,
    DatasetManifest,
    ResolvedTask,
    validate_dataset_id,
)
from ageval.config.errors import (
    ERROR_HARBOR_LAYOUT_MIX,
    ERROR_HARBOR_NETWORK,
    ERROR_HARBOR_REGISTRY,
    ERROR_HARBOR_UNSUPPORTED,
    ERROR_INVALID_OVERRIDE,
    ERROR_INVALID_PACKAGE,
    ERROR_INVALID_SCHEMA,
    ERROR_MISSING_REFERENCE,
    ERROR_UNKNOWN_PACKAGE_PATH,
    ERROR_UNKNOWN_TASK,
    ConfigError,
)

LAYOUT_AGEVAL = "ageval"
LAYOUT_HARBOR = "harbor"
LAYOUTS = frozenset({LAYOUT_AGEVAL, LAYOUT_HARBOR})

# Stable identity when the tree has no ageval.yaml. The directory name is the id.
HARBOR_DATASET_VERSION = "1"
HARBOR_ROLE = "solver"

RUN_ENTRYPOINT = "ageval.harbor.run:run"
EVAL_ENTRYPOINT = "ageval.harbor.evaluate:evaluate"
REWARD_JSON = "/logs/verifier/reward.json"
REWARD_TEXT = "/logs/verifier/reward.txt"
TEST_SCRIPT = "/tests/test.sh"
SCORING_ENV = "verifier"

_ALLOWED_FILES = frozenset(
    {"task.toml", "instruction.md", "README.md", ".gitignore", "profiles.yaml"}
)
_ALLOWED_DIRS = frozenset({"environment", "tests", "solution"})
_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "version",
        "task",
        "metadata",
        "verifier",
        "agent",
        "environment",
        "solution",
        "source",
        "artifacts",
    }
)
_ENV_KEYS = frozenset(
    {
        "build_timeout_sec",
        "docker_image",
        "os",
        "cpus",
        "memory_mb",
        "memory",
        "storage_mb",
        "storage",
        "gpus",
        "gpu_types",
        "tpu",
        "mcp_servers",
        "env",
        "skills_dir",
        "healthcheck",
        "workdir",
        "user",
        "allow_internet",
        "network_mode",
        "allowed_hosts",
    }
)
_AGENT_KEYS = frozenset({"timeout_sec", "user", "network_mode", "allowed_hosts"})
_VERIFIER_KEYS = frozenset(
    {
        "timeout_sec",
        "env",
        "user",
        "environment_mode",
        "environment",
        "collect",
        "network_mode",
        "allowed_hosts",
    }
)
_TASK_KEYS = frozenset({"name", "authors"})
_COMPOSE_NAMES = ("compose.yaml", "docker-compose.yaml")
_SIZE_RE = re.compile(r"^([0-9]*\.?[0-9]+)\s*([KMG])$", re.IGNORECASE)

HarborKind = Literal["task", "task-set"]


def require_layout(value: str) -> str:
    """``ageval`` (default) or ``harbor``. Anything else is ``invalid_override``."""
    if not isinstance(value, str):
        raise ConfigError(
            ERROR_INVALID_OVERRIDE,
            "--layout must be ageval or harbor",
            location="--layout",
        )
    text = value.strip()
    if text not in LAYOUTS:
        raise ConfigError(
            ERROR_INVALID_OVERRIDE,
            f"unknown --layout {value!r}; expected ageval or harbor",
            location="--layout",
        )
    return text


def is_harbor_tree(root: Path) -> bool:
    """True when a git checkout is a Harbor task, task-set, or rejected index.

    ``registry.json`` counts so the fetch succeeds and lock can raise
    ``harbor_registry_rejected`` instead of "ageval.yaml not found".
    """
    if not root.is_dir():
        return False
    if (root / "registry.json").is_file() or (root / "task.toml").is_file():
        return True
    for child in root.iterdir():
        if child.is_dir() and not child.name.startswith(".") and (child / "task.toml").is_file():
            return True
    return False


@dataclass(frozen=True, slots=True)
class HarborRoot:
    """One CLI path: a single task directory or an implicit task-set."""

    root: Path
    kind: HarborKind
    manifest: DatasetManifest
    task_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HarborSpec:
    """Mapped task plus the lock-reference overlay the ageval allowlist cannot express."""

    document: dict[str, Any]
    refs: dict[str, Any]


def open_harbor_root(dataset_root: Path) -> HarborRoot:
    """Classify *dataset_root*. Does not parse every ``task.toml`` field."""
    root = dataset_root.expanduser().resolve(strict=False)
    if not root.is_dir():
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            f"dataset root is not a directory: {dataset_root}",
            location=str(dataset_root),
        )
    if (root / "registry.json").is_file():
        raise ConfigError(
            ERROR_HARBOR_REGISTRY,
            "Harbor registry.json indexes are not accepted; pass the task or task-set directory",
            location="registry.json",
        )
    _reject_converted_member(root)
    if (root / "task.toml").is_file():
        _require_task_files(root)
        return HarborRoot(
            root=root,
            kind="task",
            manifest=_manifest(root),
            task_ids=(root.name,),
        )
    ids = _task_set_ids(root)
    return HarborRoot(
        root=root,
        kind="task-set",
        manifest=_manifest(root),
        task_ids=tuple(ids),
    )


def resolve_harbor_member(opened: HarborRoot, task_id: str | None) -> ResolvedTask:
    """One member. A single task rejects ``--task``; a task-set requires it."""
    if opened.kind == "task":
        if task_id and str(task_id).strip():
            raise ConfigError(
                ERROR_INVALID_OVERRIDE,
                "--task is not valid for a single Harbor task directory",
                location="--task",
            )
        tid = opened.root.name
        task_dir = opened.root
    else:
        if not task_id or not str(task_id).strip():
            raise ConfigError(
                ERROR_INVALID_OVERRIDE,
                "--task is required to lock one member of a Harbor task-set",
                location="--task",
            )
        tid = str(task_id).strip()
        if tid not in opened.task_ids:
            raise ConfigError(
                ERROR_UNKNOWN_TASK,
                f"unknown task_id: {tid!r} (not a member of this Harbor task-set)",
                location=tid,
            )
        task_dir = opened.root / tid
    return ResolvedTask(
        dataset_root=opened.root,
        task_id=tid,
        task_dir=task_dir,
        task_config_path=task_dir / "task.toml",
        dataset_id=opened.manifest.dataset_id,
        dataset_version=opened.manifest.version,
    )


def task_for_probe(package: str, layout: str, task_ids: list[str]) -> str:
    """The one task ``--probe`` locks. Harbor single-task directories omit ``--task``."""
    from ageval.registry.resolve import resolve_dataset_root

    chosen = require_layout(layout)
    if chosen != LAYOUT_HARBOR:
        if len(task_ids) != 1:
            raise ConfigError(ERROR_INVALID_OVERRIDE, "probe requires --task", location="--task")
        return task_ids[0]
    root = resolve_dataset_root(package, layout=chosen)
    opened = open_harbor_root(root)
    if opened.kind == "task":
        if task_ids:
            raise ConfigError(
                ERROR_INVALID_OVERRIDE,
                "--task is not valid for a single Harbor task directory",
                location="--task",
            )
        return opened.task_ids[0]
    if len(task_ids) != 1:
        raise ConfigError(
            ERROR_INVALID_OVERRIDE,
            "probe requires one --task for a Harbor task-set",
            location="--task",
        )
    if task_ids[0] not in opened.task_ids:
        raise ConfigError(
            ERROR_UNKNOWN_TASK,
            f"unknown task_id: {task_ids[0]!r} (not a member of this Harbor task-set)",
            location="--task",
        )
    return task_ids[0]


def filter_harbor_tasks(opened: HarborRoot, selected: list[str]) -> list[str]:
    """Suite filter. A single task rejects any ``--task``; a task-set may filter."""
    if opened.kind == "task":
        if selected:
            raise ConfigError(
                ERROR_INVALID_OVERRIDE,
                "--task is not valid for a single Harbor task directory",
                location="--task",
            )
        return list(opened.task_ids)
    if not selected:
        return list(opened.task_ids)
    unknown = [item for item in selected if item not in opened.task_ids]
    if unknown:
        raise ConfigError(
            ERROR_UNKNOWN_TASK,
            f"unknown task_id: {unknown[0]!r} (not a member of this Harbor task-set)",
            location=unknown[0],
        )
    return list(selected)


def load_harbor_spec(task_dir: Path, task_id: str) -> HarborSpec:
    """Read ``task.toml`` and return the synthetic task document plus ref overlay."""
    root = task_dir.expanduser().resolve(strict=False)
    if root.name != task_id:
        raise ConfigError(
            ERROR_UNKNOWN_TASK,
            f"task_id mismatch: directory={root.name!r} cli={task_id!r}",
            location="/task_id",
        )
    _reject_converted_member(root)
    _require_task_files(root)
    _reject_unknown_top_level(root)
    raw = _read_toml(root / "task.toml")
    return _spec_from_toml(raw, task_id=task_id, root=root)


def compute_harbor_eval_digest(root: Path, opened: HarborRoot) -> str:
    """Scoring digest for a Harbor tree that has no ``ageval.yaml``.

    Covers ``task.toml``, ``instruction.md``, and the ``tests``, ``environment``,
    and ``solution`` directories. Profiles and README files stay out.
    """
    import hashlib

    from ageval.registry.digest import file_sha256

    bases = (
        [opened.root] if opened.kind == "task" else [opened.root / tid for tid in opened.task_ids]
    )
    rels: set[str] = set()
    for base in bases:
        for name in ("task.toml", "instruction.md"):
            path = base / name
            if path.is_file():
                rels.add(path.relative_to(root).as_posix())
        for dirname in ("tests", "environment", "solution"):
            folder = base / dirname
            if not folder.is_dir():
                continue
            for file_path in sorted(folder.rglob("*")):
                if not file_path.is_file():
                    continue
                if "__pycache__" in file_path.parts or file_path.name.endswith(".pyc"):
                    continue
                rels.add(file_path.relative_to(root).as_posix())
    lines = [f"{file_sha256(root / rel)}  {rel}\n" for rel in sorted(rels)]
    blob = "".join(lines).encode("utf-8")
    return f"sha256:{hashlib.sha256(blob).hexdigest()}"


def expand_harbor_env(env: dict[str, str]) -> dict[str, str]:
    """Resolve ``${VAR}`` templates in memory. The lock keeps the authored text."""
    from ageval.config.env_refs import expand_embedded_env

    return {
        key: expand_embedded_env(value, location=f"environment.env.{key}")
        for key, value in env.items()
    }


# --- classification ----------------------------------------------------------


def _manifest(root: Path) -> DatasetManifest:
    return DatasetManifest(
        format=DATASET_FORMAT,
        dataset_id=_dataset_id(root.name),
        version=HARBOR_DATASET_VERSION,
        tasks_root=".",
        description=None,
    )


def _dataset_id(name: str) -> str:
    text = name.strip().lower().replace("_", "-")
    text = re.sub(r"[^a-z0-9./-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-./")
    if not text:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"directory name {name!r} cannot be used as a dataset_id",
            location="/dataset_id",
        )
    validate_dataset_id(text)
    return text


def _reject_converted_member(root: Path) -> None:
    """An ageval port (``task.yaml`` + ``data/`` + ``evaluation/``, or ``ageval.yaml``)."""
    converted = (
        (root / "task.yaml").is_file()
        and (root / "data").is_dir()
        and (root / "evaluation").is_dir()
    )
    if converted or (root / "ageval.yaml").is_file():
        raise ConfigError(
            ERROR_HARBOR_LAYOUT_MIX,
            "path looks like an ageval package; --layout harbor does not convert it",
            location=str(root.name),
        )


def _require_task_files(task_dir: Path) -> None:
    if not (task_dir / "instruction.md").is_file():
        raise ConfigError(
            ERROR_MISSING_REFERENCE,
            "instruction.md not found",
            location="instruction.md",
        )
    if not (task_dir / "tests" / "test.sh").is_file():
        raise ConfigError(
            ERROR_MISSING_REFERENCE,
            "tests/test.sh not found",
            location="tests/test.sh",
        )


def _task_set_ids(root: Path) -> list[str]:
    ids: list[str] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        if not child.is_dir():
            continue
        if (child / "task.toml").is_file():
            _reject_converted_member(child)
            ids.append(child.name)
            continue
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            f"task-set child {child.name!r} is not a Harbor task (missing task.toml)",
            location=child.name,
        )
    if not ids:
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            "not a Harbor task or task-set (no task.toml)",
            location=str(root),
        )
    return ids


def _reject_unknown_top_level(root: Path) -> None:
    for child in root.iterdir():
        name = child.name
        if name.startswith(".") or name == "__pycache__":
            continue
        if child.is_dir():
            if name not in _ALLOWED_DIRS:
                raise ConfigError(
                    ERROR_UNKNOWN_PACKAGE_PATH,
                    f"unknown top-level directory: {name}",
                    location=name,
                )
        elif name not in _ALLOWED_FILES:
            raise ConfigError(
                ERROR_UNKNOWN_PACKAGE_PATH,
                f"unknown top-level file: {name}",
                location=name,
            )


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            f"cannot read task.toml: {exc}",
            location="task.toml",
        ) from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"invalid task.toml: {exc}",
            location="task.toml",
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(
            ERROR_INVALID_SCHEMA, "task.toml root must be a table", location="task.toml"
        )
    return data


# --- task.toml → ageval document --------------------------------------------


def _spec_from_toml(raw: dict[str, Any], *, task_id: str, root: Path) -> HarborSpec:
    if "steps" in raw:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            "multi-step [[steps]] tasks are not supported",
            location="steps",
        )
    unknown = sorted(set(raw) - _ROOT_KEYS)
    if unknown:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            f"unsupported task.toml keys: {unknown}",
            location="task.toml",
        )
    _check_task_name(raw.get("task"), task_id)
    gaps: list[str] = []
    parameters: dict[str, Any] = {
        "package_layout": LAYOUT_HARBOR,
        "align_app": True,
        "drop_compose_main": True,
        "harbor_test_script": TEST_SCRIPT,
        "harbor_reward_json": REWARD_JSON,
        "harbor_reward_text": REWARD_TEXT,
        "harbor_scoring_env": SCORING_ENV,
    }
    limits: dict[str, Any] = {}
    env = _table(raw.get("environment"), "environment")
    _map_environment(env, parameters=parameters, limits=limits, gaps=gaps)
    agent = _table(raw.get("agent"), "agent")
    _map_agent(agent, limits=limits, parameters=parameters)
    verifier = _table(raw.get("verifier"), "verifier")
    evaluation, uploads, verifier_image = _map_verifier(
        verifier, root=root, parameters=parameters, limits=limits, gaps=gaps
    )
    attach_collect(evaluation, raw, gaps=gaps)
    _map_solution(raw.get("solution"), gaps=gaps)
    _require_image_or_environment(root, parameters)
    if (
        not parameters.get("docker_image")
        and not (root / "environment" / "Dockerfile").is_file()
        and _compose_rel(root) is not None
    ):
        gaps.append("compose_main_is_not_the_attempt_image")
    if gaps:
        parameters["harbor_known_gaps"] = gaps

    document: dict[str, Any] = {
        "format": "ageval.task/1",
        "task_id": task_id,
        "agent_profiles": [{"id": HARBOR_ROLE}],
        "parameters": parameters,
        "limits": {**DEFAULTS["limits"], **limits},
        "artifacts": {"publishable": []},
        "evaluation": evaluation,
        "requires": {},
    }
    refs = _ref_overlay(
        root,
        parameters=parameters,
        uploads=uploads,
        verifier_image=verifier_image,
    )
    return HarborSpec(document=document, refs=refs)


def _table(value: object, location: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(ERROR_INVALID_SCHEMA, f"{location} must be a table", location=location)
    return value


def _check_task_name(task: object, task_id: str) -> None:
    if task is None:
        return
    if not isinstance(task, dict):
        raise ConfigError(ERROR_INVALID_SCHEMA, "[task] must be a table", location="task")
    unknown = sorted(set(task) - _TASK_KEYS)
    if unknown:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            f"unsupported [task] keys: {unknown}",
            location="task",
        )
    name = task.get("name")
    if name is None:
        return
    if not isinstance(name, str) or name != task_id:
        raise ConfigError(
            ERROR_UNKNOWN_TASK,
            f"[task].name {name!r} must match the directory name {task_id!r}",
            location="task.name",
        )


def _map_environment(
    env: dict[str, Any],
    *,
    parameters: dict[str, Any],
    limits: dict[str, Any],
    gaps: list[str],
) -> None:
    unknown = sorted(set(env) - _ENV_KEYS)
    if unknown:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            f"unsupported [environment] keys: {unknown}",
            location="environment",
        )
    if "build_timeout_sec" in env:
        limits["environment_seconds"] = _positive_seconds(
            env.get("build_timeout_sec"), "environment.build_timeout_sec"
        )
        gaps.append("build_timeout_sec_bounds_the_environment_phase")
    os_name = env.get("os", "linux")
    if not isinstance(os_name, str) or os_name.strip().lower() != "linux":
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            "only environment.os = linux is supported",
            location="environment.os",
        )
    if env.get("tpu") is not None:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            "TPU environments are not supported",
            location="environment.tpu",
        )
    servers = env.get("mcp_servers") or []
    if servers:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            "MCP servers are not supported",
            location="environment.mcp_servers",
        )
    if env.get("healthcheck") is not None:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            "healthchecks are not supported",
            location="environment.healthcheck",
        )
    if env.get("skills_dir"):
        gaps.append("skills_dir")
    if "storage_mb" in env or "storage" in env:
        gaps.append("storage_mb")
    image = env.get("docker_image")
    if image is not None:
        if not isinstance(image, str) or not image.strip():
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "environment.docker_image must be a non-empty string",
                location="environment.docker_image",
            )
        parameters["docker_image"] = image.strip()
    _copy_resources(env, parameters, prefix="")
    _map_network(env, parameters, location="environment")
    _map_user(env.get("user"), parameters, key="harbor_user", location="environment.user")
    workdir = env.get("workdir")
    if workdir is not None:
        if not isinstance(workdir, str) or not workdir.startswith("/"):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "environment.workdir must be an absolute path",
                location="environment.workdir",
            )
        parameters["harbor_workdir"] = workdir
    mapped_env = _string_map(env.get("env"), location="environment.env")
    if mapped_env:
        parameters["main_environment"] = mapped_env


def _map_agent(
    agent: dict[str, Any], *, limits: dict[str, Any], parameters: dict[str, Any]
) -> None:
    unknown = sorted(set(agent) - _AGENT_KEYS)
    if unknown:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            f"unsupported [agent] keys: {unknown}",
            location="agent",
        )
    _reject_phase_network(agent, location="agent")
    # Absent agent.timeout_sec must not inherit verifier.timeout_sec.
    if "timeout_sec" in agent:
        limits["wall_time_seconds"] = _positive_seconds(
            agent.get("timeout_sec"), "agent.timeout_sec"
        )
    _map_user(agent.get("user"), parameters, key="harbor_user", location="agent.user")


def _map_verifier(
    verifier: dict[str, Any],
    *,
    root: Path,
    parameters: dict[str, Any],
    limits: dict[str, Any],
    gaps: list[str],
) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, str] | None]:
    unknown = sorted(set(verifier) - _VERIFIER_KEYS)
    if unknown:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            f"unsupported [verifier] keys: {unknown}",
            location="verifier",
        )
    _reject_phase_network(verifier, location="verifier")
    if "timeout_sec" in verifier:
        limits["evaluate_seconds"] = _positive_seconds(
            verifier.get("timeout_sec"), "verifier.timeout_sec"
        )
    _map_user(
        verifier.get("user"),
        parameters,
        key="harbor_verifier_user",
        location="verifier.user",
    )
    nested = verifier.get("environment")
    if isinstance(nested, dict):
        gpus = nested.get("gpus")
        if isinstance(gpus, int) and not isinstance(gpus, bool) and gpus > 0:
            parameters["verifier_gpus"] = gpus
    mode, image, preinstalled = _verifier_image(
        verifier,
        root=root,
        gaps=gaps,
        agent_image=parameters.get("docker_image")
        if isinstance(parameters.get("docker_image"), str)
        else None,
    )
    parameters["harbor_verifier_mode"] = mode
    evaluation: dict[str, Any] = {}
    if image is not None:
        evaluation["environments"] = {SCORING_ENV: image}
    uploads = [] if preinstalled else [{"source": "tests", "dest": "/tests"}]
    return evaluation, uploads, image


def _verifier_image(
    verifier: dict[str, Any],
    *,
    root: Path,
    gaps: list[str],
    agent_image: str | None,
) -> tuple[str, dict[str, str] | None, bool]:
    """Return ``(mode, named image recipe or None, tests preinstalled)``.

    ``tests/Dockerfile`` is a separate verifier image and already contains
    ``/tests/test.sh``. An explicit ``environment_mode = separate`` never falls
    back to the agent container.
    """
    nested = verifier.get("environment")
    if nested is not None and not isinstance(nested, dict):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "verifier.environment must be a table",
            location="verifier.environment",
        )
    mode_raw = verifier.get("environment_mode")
    if mode_raw is not None and mode_raw not in {"shared", "separate"}:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "verifier.environment_mode must be shared or separate",
            location="verifier.environment_mode",
        )
    if mode_raw == "shared" and nested:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "verifier.environment_mode shared cannot set verifier.environment",
            location="verifier.environment_mode",
        )
    tests_dockerfile = (root / "tests" / "Dockerfile").is_file()
    if nested:
        recipe = _environment_recipe(nested, root=root, location="verifier.environment", gaps=gaps)
        preinstalled = recipe.get("dockerfile") == "tests/Dockerfile"
        return "separate", recipe, preinstalled
    if mode_raw == "shared":
        return "shared", None, False
    if tests_dockerfile:
        return "separate", {"dockerfile": "tests/Dockerfile", "context": "tests"}, True
    if mode_raw == "separate":
        recipe = _clone_agent_environment(root, agent_image)
        return "separate", recipe, False
    return "shared", None, False


def _environment_recipe(
    env: dict[str, Any],
    *,
    root: Path,
    location: str,
    gaps: list[str],
) -> dict[str, str]:
    unknown = sorted(set(env) - _ENV_KEYS)
    if unknown:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            f"unsupported [{location}] keys: {unknown}",
            location=location,
        )
    if env.get("cpus") is not None or env.get("memory_mb") is not None or env.get("memory"):
        gaps.append("verifier_cpu_memory")
    if "storage_mb" in env or "storage" in env:
        gaps.append("verifier_storage_mb")
    image = env.get("docker_image")
    if isinstance(image, str) and image.strip():
        return {"docker_image": image.strip()}
    if (root / "tests" / "Dockerfile").is_file() and location.startswith("verifier"):
        return {"dockerfile": "tests/Dockerfile", "context": "tests"}
    if (root / "environment" / "Dockerfile").is_file():
        return {"dockerfile": "environment/Dockerfile", "context": "environment"}
    raise ConfigError(
        ERROR_MISSING_REFERENCE,
        f"{location} needs docker_image or a Dockerfile",
        location=location,
    )


def _clone_agent_environment(root: Path, agent_image: str | None) -> dict[str, str]:
    if agent_image:
        return {"docker_image": agent_image}
    if (root / "environment" / "Dockerfile").is_file():
        return {"dockerfile": "environment/Dockerfile", "context": "environment"}
    raise ConfigError(
        ERROR_MISSING_REFERENCE,
        "verifier.environment_mode separate needs tests/Dockerfile, "
        "[verifier.environment], or environment/Dockerfile",
        location="verifier.environment_mode",
    )


def _map_solution(solution: object, *, gaps: list[str]) -> None:
    if solution is None:
        return
    if not isinstance(solution, dict):
        raise ConfigError(ERROR_INVALID_SCHEMA, "solution must be a table", location="solution")
    unknown = sorted(set(solution) - {"env"})
    if unknown:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            f"unsupported [solution] keys: {unknown}",
            location="solution",
        )
    if solution.get("env"):
        gaps.append("solution.env")


def _require_image_or_environment(root: Path, parameters: dict[str, Any]) -> None:
    has_image = bool(parameters.get("docker_image"))
    has_env = (root / "environment").is_dir()
    if not has_image and not has_env:
        raise ConfigError(
            ERROR_MISSING_REFERENCE,
            "Harbor task needs environment/ or environment.docker_image",
            location="environment",
        )
    if has_env and not has_image and not (root / "environment" / "Dockerfile").is_file():
        compose = any((root / "environment" / name).is_file() for name in _COMPOSE_NAMES)
        if not compose:
            raise ConfigError(
                ERROR_MISSING_REFERENCE,
                "environment/ needs a Dockerfile or a compose file when docker_image is unset",
                location="environment/Dockerfile",
            )


def _ref_overlay(
    root: Path,
    *,
    parameters: dict[str, Any],
    uploads: list[dict[str, str]],
    verifier_image: dict[str, str] | None,
) -> dict[str, Any]:
    refs: dict[str, Any] = {
        "run_entrypoint": RUN_ENTRYPOINT,
        "run_module_file": "ageval.harbor.run",
        "evaluation_entrypoint": EVAL_ENTRYPOINT,
        "evaluation_module_file": "ageval.harbor.evaluate",
    }
    if uploads:
        refs["package_uploads"] = uploads
    if not parameters.get("docker_image") and (root / "environment" / "Dockerfile").is_file():
        refs["environment_build_context"] = "environment"
        refs["environment_dockerfile"] = "environment/Dockerfile"
    compose = _compose_rel(root)
    if compose is not None:
        refs["environment_compose"] = compose
    if verifier_image and verifier_image.get("context"):
        refs["evaluation_build_context"] = verifier_image["context"]
    return refs


def _compose_rel(root: Path) -> str | None:
    env = root / "environment"
    if (env / "compose.yaml").is_file():
        return "environment/compose.yaml"
    if (env / "docker-compose.yaml").is_file():
        return "environment/docker-compose.yaml"
    return None


def attach_collect(
    evaluation: dict[str, Any],
    raw: dict[str, Any],
    *,
    gaps: list[str],
) -> None:
    """Fill ``evaluation.collect``: commands first, then artifact paths."""
    verifier = _table(raw.get("verifier"), "verifier")
    rows = _collect_rows(verifier.get("collect"), raw.get("artifacts"), gaps=gaps)
    if rows:
        evaluation["collect"] = rows


def _collect_rows(
    commands: object,
    raw_artifacts: object,
    *,
    gaps: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if commands is not None:
        if not isinstance(commands, list):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "verifier.collect must be an array",
                location="verifier.collect",
            )
        for index, item in enumerate(commands):
            rows.append(_one_command(item, f"verifier.collect[{index}]", gaps=gaps))
    if raw_artifacts is not None:
        if not isinstance(raw_artifacts, list):
            raise ConfigError(
                ERROR_INVALID_SCHEMA, "artifacts must be an array", location="artifacts"
            )
        for index, item in enumerate(raw_artifacts):
            rows.append(_one_artifact(item, f"artifacts[{index}]", gaps=gaps))
    return rows


def _one_command(item: object, location: str, *, gaps: list[str]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ConfigError(ERROR_INVALID_SCHEMA, "collect entry must be a table", location=location)
    unknown = sorted(set(item) - {"command", "service", "timeout_sec", "user"})
    if unknown:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            f"unsupported collect keys: {unknown}",
            location=location,
        )
    command = item.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ConfigError(
            ERROR_INVALID_SCHEMA, "collect command must be a non-empty string", location=location
        )
    row: dict[str, Any] = {"command": command}
    service = _optional_service(item.get("service"), location)
    if service is not None and service != "main":
        row["service"] = service
    if "timeout_sec" in item:
        row["timeout_sec"] = _positive_seconds(item.get("timeout_sec"), f"{location}.timeout_sec")
    if item.get("user") is not None:
        _uid_only(item.get("user"), f"{location}.user")
        gaps.append("verifier.collect.user")
    return row


def _one_artifact(item: object, location: str, *, gaps: list[str]) -> dict[str, Any]:
    if isinstance(item, str):
        return {"path": _absolute_path(item, location)}
    if not isinstance(item, dict):
        raise ConfigError(
            ERROR_INVALID_SCHEMA, "artifact must be a path or table", location=location
        )
    unknown = sorted(set(item) - {"source", "destination", "exclude", "service"})
    if unknown:
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            f"unsupported artifact keys: {unknown}",
            location=location,
        )
    source = item.get("source")
    if not isinstance(source, str):
        raise ConfigError(ERROR_INVALID_SCHEMA, "artifact source is required", location=location)
    row: dict[str, Any] = {"path": _absolute_path(source, location)}
    service = _optional_service(item.get("service"), location)
    if service is not None and service != "main":
        row["service"] = service
    exclude = item.get("exclude") or []
    if exclude:
        if not isinstance(exclude, list) or not all(
            isinstance(part, str) and part for part in exclude
        ):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "artifact exclude must be a list of strings",
                location=location,
            )
        row["exclude"] = list(exclude)
    if item.get("destination"):
        gaps.append("artifact.destination")
    return row


def _absolute_path(value: str, location: str) -> str:
    text = value.strip()
    if not text.startswith("/") or ".." in Path(text).parts:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "artifact path must be absolute and must not contain ..",
            location=location,
        )
    return text.rstrip("/") or "/"


def _optional_service(value: object, location: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            ERROR_INVALID_SCHEMA, "service must be a non-empty string", location=location
        )
    return value.strip()


# --- scalars -----------------------------------------------------------------


def _map_network(env: dict[str, Any], parameters: dict[str, Any], *, location: str) -> None:
    if env.get("allowed_hosts"):
        raise ConfigError(
            ERROR_HARBOR_NETWORK,
            "network allowlists are not supported and are not treated as public",
            location=f"{location}.allowed_hosts",
        )
    mode = env.get("network_mode")
    if mode is None:
        allow = env.get("allow_internet")
        if allow is None:
            parameters["harbor_network"] = "public"
            return
        if not isinstance(allow, bool):
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "allow_internet must be a boolean",
                location=f"{location}.allow_internet",
            )
        parameters["harbor_network"] = "public" if allow else "no-network"
        return
    if not isinstance(mode, str) or mode not in {"public", "no-network", "allowlist"}:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "network_mode must be public, no-network, or allowlist",
            location=f"{location}.network_mode",
        )
    if mode == "allowlist":
        raise ConfigError(
            ERROR_HARBOR_NETWORK,
            "network_mode allowlist is not supported and is not treated as public",
            location=f"{location}.network_mode",
        )
    parameters["harbor_network"] = mode


def _reject_phase_network(table: dict[str, Any], *, location: str) -> None:
    if table.get("network_mode") is not None or table.get("allowed_hosts"):
        raise ConfigError(
            ERROR_HARBOR_NETWORK,
            f"[{location}] network overrides are not supported",
            location=f"{location}.network_mode",
        )


def _map_user(value: object, parameters: dict[str, Any], *, key: str, location: str) -> None:
    if value is None:
        return
    # Agent user overrides environment user when both are set. Caller order is
    # environment then agent, so a later call replaces harbor_user.
    parameters[key] = _uid_only(value, location)


def _uid_only(value: object, location: str) -> str:
    if isinstance(value, bool) or isinstance(value, str) and not value.strip().isdigit():
        raise ConfigError(
            ERROR_HARBOR_UNSUPPORTED,
            "user must be a numeric uid; usernames are rejected",
            location=location,
        )
    if isinstance(value, int):
        if value < 0:
            raise ConfigError(ERROR_INVALID_SCHEMA, "user uid must be >= 0", location=location)
        return str(value)
    if isinstance(value, str) and value.strip().isdigit():
        return str(int(value.strip()))
    raise ConfigError(
        ERROR_HARBOR_UNSUPPORTED,
        "user must be a numeric uid; usernames are rejected",
        location=location,
    )


def _copy_resources(env: dict[str, Any], parameters: dict[str, Any], *, prefix: str) -> None:
    if "cpus" in env and env.get("cpus") not in (None, 0):
        parameters[f"{prefix}cpus" if prefix else "cpus"] = env["cpus"]
    memory = env.get("memory_mb")
    if memory is None and "memory" in env:
        memory = _size_to_mb(env.get("memory"), "environment.memory")
    if isinstance(memory, int | float) and not isinstance(memory, bool) and memory:
        parameters["memory_mb" if not prefix else f"{prefix}memory_mb"] = int(memory)
    gpus = env.get("gpus")
    if isinstance(gpus, int) and not isinstance(gpus, bool) and gpus > 0:
        parameters["gpus" if not prefix else f"{prefix}gpus"] = gpus
    gpu_types = env.get("gpu_types")
    if gpu_types:
        parameters["gpu_types"] = gpu_types
    verifier_gpus = env.get("verifier_gpus")
    if isinstance(verifier_gpus, int) and not isinstance(verifier_gpus, bool) and verifier_gpus > 0:
        parameters["verifier_gpus"] = verifier_gpus


def _size_to_mb(value: object, location: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str) or not _SIZE_RE.fullmatch(value.strip()):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "memory must be a number of MB or a size like 512M or 2G",
            location=location,
        )
    match = _SIZE_RE.fullmatch(value.strip())
    assert match is not None
    number = float(match.group(1))
    unit = match.group(2).upper()
    if unit == "G":
        return int(number * 1024)
    if unit == "M":
        return int(number)
    return int(number / 1024)


def _positive_seconds(value: object, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(
            ERROR_INVALID_SCHEMA, "timeout must be a positive number of seconds", location=location
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise ConfigError(ERROR_INVALID_SCHEMA, "timeout must be finite", location=location)
    if value <= 0:
        raise ConfigError(ERROR_INVALID_SCHEMA, "timeout must be > 0", location=location)
    return int(math.ceil(float(value)))


def _string_map(value: object, *, location: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(ERROR_INVALID_SCHEMA, "env must be a table of strings", location=location)
    out: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ConfigError(
                ERROR_INVALID_SCHEMA, "env keys and values must be strings", location=location
            )
        out[key] = item
    return out
