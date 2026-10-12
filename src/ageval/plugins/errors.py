"""Stable error kinds for the extension registry / resolve path."""

from __future__ import annotations


class ExtensionRegistryError(Exception):
    """Base for extension registry failures (fail closed)."""

    kind: str = "extension_registry_error"

    def __init__(self, message: str, *, kind: str | None = None) -> None:
        super().__init__(message)
        if kind is not None:
            self.kind = kind
        self.message = message


class UnknownExtensionSlotError(ExtensionRegistryError):
    kind = "unknown_extension_slot"


class ExtensionPluginNotFoundError(ExtensionRegistryError):
    kind = "extension_plugin_not_found"


class ExtensionMaterializeError(ExtensionRegistryError):
    kind = "extension_materialize_failed"


class ServiceNotFoundError(ExtensionRegistryError):
    kind = "service_not_found"


class ServiceConflictError(ExtensionRegistryError):
    kind = "service_conflict"


class InjectUnsatisfiedError(ExtensionRegistryError):
    kind = "inject_unsatisfied"


class PluginContractError(ExtensionRegistryError):
    """Class contract failure at registration or at lock.

    Registration: the class is the wrong base, a required method is missing,
    a true capability has no callable method, or ``extra_allowlist`` /
    ``supported_apis`` / ``supported_model_fields`` is undeclared. An explicit
    empty ``extra_allowlist`` is valid.

    Lock: ``requires_environment`` is set and the environment inject is
    missing or short on capabilities, or strict mode rejects a yaml-only
    executor that cannot declare an allowlist. A bad model profile raises
    ``ModelConfigError``. Transport failures stay on the upstream-stall path.
    """

    kind = "plugin_contract"
