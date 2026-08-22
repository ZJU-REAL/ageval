"""First-party contrib short ids: bundled with ageval, not Hub packages."""

from __future__ import annotations

from ageval.plugins.manifest import PluginManifestError, split_plugin_id

RESERVED_PLUGIN_IDS: frozenset[str] = frozenset(
    {
        "local",
        "docker",
        "e2b",
        "ssh",
        "daytona",
        "acp",
        "openai-http",
    }
)


def reserved_short_id(raw: str) -> str | None:
    """Return the reserved short id if *raw* is or aliases one (path, locator, org/name)."""
    text = raw.strip()
    if not text:
        return None
    locator = text.split("@", 1)[0].strip()
    if not locator:
        return None
    _org, name = split_plugin_id(locator)
    key = name.casefold()
    for item in RESERVED_PLUGIN_IDS:
        if item.casefold() == key:
            return item
    return None


def reject_reserved_plugin_id(plugin_id: str) -> None:
    hit = reserved_short_id(plugin_id)
    if hit is None:
        return
    raise PluginManifestError(
        f"{hit} ships with ageval; it is not a Hub package",
        kind="plugin_id_reserved",
    )
