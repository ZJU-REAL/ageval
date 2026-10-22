"""Config Core error types.

Every failure that must reach the operator maps to a stable ``error_code`` and
CLI exit 2. Messages may include JSON Pointers or package-relative paths; they
must never include host secrets or raw stack traces on the public path.
"""

from __future__ import annotations


class ConfigError(Exception):
    """Fail-closed Config error with a stable operator-facing code.

    A plain exception on purpose: a frozen dataclass cannot carry the traceback
    Python assigns while an exception travels, which turns any raise through a
    context manager into an unrelated TypeError.
    """

    def __init__(self, error_code: str, message: str, location: str | None = None) -> None:
        super().__init__(error_code, message, location)
        self.error_code = error_code
        self.message = message
        self.location = location

    def __str__(self) -> str:
        if self.location:
            return f"{self.error_code}: {self.message} ({self.location})"
        return f"{self.error_code}: {self.message}"

    def __repr__(self) -> str:
        return (
            f"ConfigError(error_code={self.error_code!r}, message={self.message!r}, "
            f"location={self.location!r})"
        )


# Stable public error codes.
ERROR_INVALID_PACKAGE = "invalid_package"
ERROR_INVALID_FORMAT = "invalid_format"
ERROR_UNKNOWN_TASK = "unknown_task"
ERROR_UNKNOWN_PROFILE = "unknown_profile"
ERROR_UNSUPPORTED_CAPABILITY = "unsupported_capability"
ERROR_PATH_OUTSIDE_PACKAGE = "path_outside_package"
ERROR_UNKNOWN_PACKAGE_PATH = "unknown_package_path"
ERROR_INVALID_OVERRIDE = "invalid_override"
ERROR_INVALID_SCHEMA = "invalid_schema"
ERROR_MISSING_REFERENCE = "missing_reference"
# Role slot declared in task.yaml but no job binding from profiles.yaml / CLI (#59).
ERROR_MISSING_BINDING = "missing_binding"
# Harbor intake (`--layout harbor`). Distinct from a missing ageval.yaml.
ERROR_HARBOR_REGISTRY = "harbor_registry_rejected"
ERROR_HARBOR_LAYOUT_MIX = "harbor_layout_mix"
ERROR_HARBOR_NETWORK = "harbor_network_unsupported"
ERROR_HARBOR_UNSUPPORTED = "harbor_unsupported"
