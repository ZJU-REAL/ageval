"""Host inventory for agent executor kinds + ACP entries."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from ageval.plugins.contrib.acp.child_env import entry_credentials_missing
from ageval.plugins.contrib.acp.path_probe import WhichFn, probe_commands
from ageval.plugins.contrib.acp.registry import list_entry_ids, load_acp_entries, readiness_for
from ageval.plugins.executor_capabilities import get_capabilities

_BINARY_CANDIDATES: Mapping[str, tuple[str, ...]] = {
    "acp": (),
    "openai-http": (),
    "anthropic-http": (),
    "openai": (),
}

_API_ALIASES: frozenset[str] = frozenset({"openai"})

# First-party contrib ids. Everything else joins the exclusive executor slot
# through an installed plugin.
FIRST_PARTY_KINDS: frozenset[str] = frozenset({"acp", "openai-http", "anthropic-http", "openai"})


def known_executor_kinds() -> frozenset[str]:
    """Every plugin registered on the exclusive ``executor`` slot."""
    from ageval.plugins.bootstrap import ensure_bootstrapped
    from ageval.plugins.slots import EXECUTOR

    return frozenset(ensure_bootstrapped().plugins_for_slot(EXECUTOR))


def supported_executor_kinds() -> list[str]:
    return sorted(known_executor_kinds())


def probe_binary(
    candidates: tuple[str, ...],
    *,
    which: WhichFn | None = None,
) -> tuple[str | None, str | None]:
    return probe_commands(candidates, which=which)


def binary_candidates_for(kind: str) -> tuple[str, ...]:
    if kind in _BINARY_CANDIDATES:
        return _BINARY_CANDIDATES[kind]
    caps = get_capabilities(kind)
    if caps is not None and caps.binary:
        return (caps.binary,)
    return ()


def describe_executor(
    kind: str,
    *,
    which: WhichFn | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    caps = get_capabilities(kind)
    if caps is not None:
        mode = caps.execution_mode
    elif kind in _API_ALIASES:
        mode = "api-client"
    else:
        mode = "unknown"

    if kind not in FIRST_PARTY_KINDS and kind not in _API_ALIASES:
        return _describe_plugin_executor(kind, caps=caps, mode=mode, verbose=verbose)

    candidates = binary_candidates_for(kind)
    binary_name, binary_path = probe_binary(candidates, which=which)

    if mode in {"api-client", "acp-stdio"} or not candidates:
        binary_on_path: bool | None = None
        if mode == "acp-stdio":
            host_ready = False
            binary_name = None
        else:
            host_ready = True
            if not candidates:
                binary_name = None
    else:
        binary_on_path = binary_path is not None
        host_ready = binary_on_path

    row: dict[str, Any] = {
        "kind": kind,
        "execution_mode": mode,
        "binary": binary_name,
        "binary_on_path": binary_on_path,
        "binary_path": binary_path,
        "host_ready": host_ready,
    }
    if verbose:
        if caps is not None:
            row["credential_env_names"] = list(caps.credential_env_names)
            row["tools"] = caps.tools
            row["structured_output"] = caps.structured_output
            row["session"] = caps.session
            row["stream"] = caps.stream
        else:
            row["credential_env_names"] = []
    return row


def _describe_plugin_executor(
    kind: str,
    *,
    caps: Any,
    mode: str,
    verbose: bool,
) -> dict[str, Any]:
    """L0 host-ready from declared host_requires; never default True on missing describe()."""
    from ageval.plugins.host_requires import (
        bake_recipe_declared,
        host_requires_satisfied,
        installed_plugin,
    )
    from ageval.plugins.plugin_requires import plugin_requires_satisfied

    found = installed_plugin(kind)
    l1_declared = False
    host_ready = False
    binary_name = None
    if caps is not None and getattr(caps, "binary", ""):
        binary_name = caps.binary
    if found is not None:
        manifest, root = found
        l1_declared = bake_recipe_declared(manifest, root)
        requires_ok = plugin_requires_satisfied(manifest.plugin_requires)
        if not requires_ok:
            host_ready = False
        elif manifest.host_requires:
            host_ready = host_requires_satisfied(manifest.host_requires, root=root)
        elif caps is not None:
            host_ready = True
    row: dict[str, Any] = {
        "kind": kind,
        "execution_mode": mode,
        "binary": binary_name,
        "binary_on_path": None,
        "binary_path": None,
        "host_ready": host_ready,
        "bake_recipe_declared": l1_declared,
    }
    if verbose:
        if caps is not None:
            row["credential_env_names"] = list(caps.credential_env_names)
            row["tools"] = caps.tools
            row["structured_output"] = caps.structured_output
            row["session"] = caps.session
            row["stream"] = caps.stream
        else:
            row["credential_env_names"] = []
        if found is not None and found[0].host_requires:
            row["host_requires"] = [
                {
                    **({"import": item.import_name} if item.import_name else {}),
                    **({"file": item.file} if item.file else {}),
                    **({"hint": item.hint} if item.hint else {}),
                }
                for item in found[0].host_requires
            ]
    return row


def describe_acp_entry(
    entry_id: str,
    *,
    which: WhichFn | None = None,
    verbose: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    entries = load_acp_entries()
    desc = entries[entry_id]
    ready = readiness_for(desc, which=which)
    host = environ if environ is not None else os.environ
    row: dict[str, Any] = {
        "kind": "acp",
        "entry_id": desc.entry_id,
        "execution_mode": "acp-stdio",
        "integration_mode": desc.integration_mode,
        "engine_command": desc.engine_command,
        "acp_command": list(desc.acp_command),
        "acp_version": desc.acp_version,
        "engine_version": desc.engine_version,
        "engine_ready": ready["engine_ready"],
        "acp_entry_ready": ready["acp_entry_ready"],
        "readiness": ready["readiness"],
        "host_ready": ready["readiness"] == "ready",
        "binary": ready.get("acp_binary"),
        "binary_on_path": ready["acp_entry_ready"],
        "binary_path": ready.get("acp_path") if verbose else None,
        "source": desc.source,
    }
    if verbose:
        row["credential_env_names"] = list(desc.credential_env_names)
        row["keyless_auth"] = desc.keyless_auth
        row["credential_missing"] = entry_credentials_missing(
            desc.credential_env_names,
            host_environ=host,
        )
        row["install_command"] = desc.install_command
        row["descriptor_digest"] = desc.descriptor_digest
        row["model_binding"] = desc.model_binding
        row["engine_path"] = ready.get("engine_path")
        row["tools"] = "native"
        row["structured_output"] = "validated-text"
        row["session"] = "new-only"
        row["stream"] = "native-events"
    return row


def build_executor_inventory(
    *,
    which: WhichFn | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    supported = supported_executor_kinds()
    rows = [describe_executor(k, which=which, verbose=verbose) for k in supported]
    acp_rows = [describe_acp_entry(eid, which=which, verbose=verbose) for eid in list_entry_ids()]
    for row in rows:
        if row.get("kind") == "acp":
            row["host_ready"] = any(r.get("host_ready") for r in acp_rows)
            row["acp_entries_ready"] = sorted(
                r["entry_id"] for r in acp_rows if r.get("host_ready")
            )
    return {
        "supported": supported,
        "host_ready": sorted(r["kind"] for r in rows if r.get("host_ready")),
        "missing_binary": sorted(r["kind"] for r in rows if r.get("binary_on_path") is False),
        "executors": rows,
        "acp_entries": acp_rows,
    }
