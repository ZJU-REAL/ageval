"""ageval plugin subsystem: host-owned slots, service table, and registry.

Public surface for the composition root, config lock, and Agent Service.
Third-party business plugins do not live under this package.
"""

from __future__ import annotations

from ageval.plugins.base import BaseEnvironment, BaseExecutor
from ageval.plugins.conflict import ExtensionConflictError
from ageval.plugins.errors import (
    ExtensionMaterializeError,
    ExtensionPluginNotFoundError,
    ExtensionRegistryError,
    InjectUnsatisfiedError,
    PluginContractError,
    ServiceConflictError,
    ServiceNotFoundError,
    UnknownExtensionSlotError,
)
from ageval.plugins.lock_bind import extension_graph_to_lock
from ageval.plugins.protocol import (
    BindingIntent,
    ExplicitBinding,
    ExtensionGraph,
    HandlerRef,
    InjectRequirement,
    WinnerRef,
)
from ageval.plugins.registry import ExtensionRegistry, get_global_registry, reset_global_registry
from ageval.plugins.resolve import resolve
from ageval.plugins.services import ServiceTable
from ageval.plugins.slots import ALL_SLOTS, SlotKind, get_slot_kind, is_slot

__all__ = [
    "ALL_SLOTS",
    "BaseEnvironment",
    "BaseExecutor",
    "BindingIntent",
    "ExplicitBinding",
    "ExtensionConflictError",
    "ExtensionGraph",
    "ExtensionMaterializeError",
    "ExtensionPluginNotFoundError",
    "ExtensionRegistry",
    "ExtensionRegistryError",
    "HandlerRef",
    "InjectRequirement",
    "InjectUnsatisfiedError",
    "PluginContractError",
    "ServiceConflictError",
    "ServiceNotFoundError",
    "ServiceTable",
    "SlotKind",
    "UnknownExtensionSlotError",
    "WinnerRef",
    "extension_graph_to_lock",
    "get_global_registry",
    "get_slot_kind",
    "is_slot",
    "reset_global_registry",
    "resolve",
]
