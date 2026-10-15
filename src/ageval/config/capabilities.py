"""Declaration-only capability catalog.

Config asks "is this declaration recognizable?" — never "is the adapter ready?".
Which box kinds and Agent backends exist is the plugin registry's answer, not a
hardcoded list here.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CapabilityCatalog(Protocol):
    """Read-only catalog used during Config validation."""

    def supports_format(self, format_id: str) -> bool:
        """Return True if the package format id is known to Config."""
        ...

    def supports_acp_entry(self, entry_id: str) -> bool:
        """Return True if the ACP entry id exists in the static entry registry."""
        ...


class DeclarationCapabilityCatalog:
    """v1 catalog: recognizes declared formats and ACP entry ids."""

    FORMATS: frozenset[str] = frozenset({"ageval.task/1"})

    def supports_format(self, format_id: str) -> bool:
        return format_id in self.FORMATS

    def supports_acp_entry(self, entry_id: str) -> bool:
        from ageval.plugins.contrib.acp.registry import peek_acp_entries

        table = peek_acp_entries()
        if not table:
            return False
        return entry_id in table
