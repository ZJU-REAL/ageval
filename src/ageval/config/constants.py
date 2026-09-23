"""Task package layout allowlists, override allowlist, and explicit defaults."""

from __future__ import annotations

from typing import Any

# Task top-level allowlist. Unknown first-level paths fail closed.
ALLOWED_TOP_LEVEL_FILES = frozenset(
    {
        "README.md",
        "task.yaml",
        "run.py",
        "evaluator.py",
        ".gitignore",
        "pyproject.toml",
        "uv.lock",
        "requirements.txt",
    }
)
ALLOWED_TOP_LEVEL_DIRS = frozenset(
    {
        "prompts",
        "schemas",
        "environment",
        "evaluation",
        "data",
        "lib",
        "upstream",
        "solution",
    }
)

# Files the task ships that Config recognizes without a yaml field.
RUN_MODULE_FILE = "run.py"
RUN_ENTRYPOINT_DEFAULT = "run:run"
EVALUATOR_MODULE_FILE = "evaluator.py"
EVALUATOR_ENTRYPOINT_DEFAULT = "evaluator:evaluate"
ENVIRONMENT_DIR = "environment"
DOCKERFILE_DEFAULT = "environment/Dockerfile"
EVALUATE_DOCKERFILE_DEFAULT = "environment/evaluate.Dockerfile"
# Named scoring hosts live under environment/evaluate/<name>/, never evaluation/.
EVALUATE_ENVIRONMENT_NAME_PATTERN = r"^[a-z][a-z0-9_-]*$"
COMPOSE_DEFAULT = "environment/compose.yaml"
SETUP_SCRIPT_DEFAULT = "environment/setup.sh"
SEED_DIR = "data"
EVALUATION_DIR = "evaluation"

# JSON Pointers that CLI ``--set`` may override.
# Intent limits are pure task contract — never job-overridable. Agent binding
# uses /agent_profiles/<role>/… (see profiles.is_profile_override_pointer).
ALLOWLISTED_OVERRIDE_POINTERS = frozenset(
    {
        "/parameters/seed",
        "/parameters/active_profile",
    }
)

# Explicit defaults applied after reading task.yaml, before overrides.
DEFAULTS: dict[str, Any] = {
    "limits": {
        "wall_time_seconds": 300,
        "environment_seconds": 600,
        "evaluate_seconds": 600,
        "agent_invocations": 1,
    },
    "artifacts": {
        "publishable": [],
    },
    "agent_profiles": [],
    "requires": {},
    "evaluation": {},
}

# Task keys that belonged to the deleted provider / harness model.
REJECTED_TASK_KEYS: dict[str, str] = {
    "harness": "declare business logic in run.py (entrypoint defaults to run:run)",
    "provider": "the box is chosen by the job: profiles.yaml environment: <kind>",
    "assurance": "kinds and capabilities replaced isolation grades",
    "environment": (
        "sidecars come from the box (compose or host.exec(service=…)); "
        "task recipes live in environment/"
    ),
}
