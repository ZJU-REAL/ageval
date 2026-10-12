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
    """Capability or method contract failure at registration.

    Distinct from ``ModelConfigError`` (bad model profile) and from transport
    failures that upstream stall may retry.
    """

    kind = "plugin_contract"
