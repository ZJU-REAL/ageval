"""Read-only Datasets, Plugins, and Agent packages for the local viewer.

Builtin rows come from the running CLI. Installed rows come from
``$AGEVAL_HOME`` index files. Roots are the package directory only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

import yaml

from ageval.agents.manifest import AgentManifest, load_agent_manifest
from ageval.agents.paths import agents_root
from ageval.agents.reserved import builtin_harness_root, builtin_harness_rows
from ageval.agents.store import load_index as load_agent_index
from ageval.agents.store import resolve_package_root as resolve_agent_root
from ageval.config.errors import ERROR_INVALID_PACKAGE, ConfigError
from ageval.plugins.manifest import PluginManifest, PluginManifestError, load_manifest
from ageval.plugins.paths import plugins_root
from ageval.plugins.reserved import RESERVED_PLUGIN_IDS
from ageval.plugins.store import load_index as load_plugin_index
from ageval.plugins.store import resolve_package_root as resolve_plugin_root
from ageval.viewer.files import contained, list_tree, read_preview
from ageval.viewer.session import OpenedDataset

# Same ids as RESERVED_PLUGIN_IDS, in the order operators see them.
BUILTIN_PLUGIN_IDS: tuple[str, ...] = (
    "local",
    "docker",
    "e2b",
    "ssh",
    "daytona",
    "acp",
    "openai-http",
    "anthropic-http",
)

if set(BUILTIN_PLUGIN_IDS) != set(RESERVED_PLUGIN_IDS):
    raise RuntimeError("builtin plugin ids drifted from RESERVED_PLUGIN_IDS")

_CONTRIB = Path(__file__).resolve().parents[1] / "plugins" / "contrib"


def dataset_package(dataset: OpenedDataset) -> dict[str, Any]:
    return {
        "ok": True,
        "kind": "dataset",
        "source": "dataset",
        "id": dataset.dataset_id,
        "version": dataset.version,
        "label": dataset.label,
        "description": dataset.description,
        "readme": _file_name(dataset.root, "README.md"),
        "manifest": _file_name(dataset.root, "ageval.yaml"),
        "profiles": _file_name(dataset.root, "profiles.yaml"),
        "read_only": True,
    }


def dataset_tree(dataset: OpenedDataset) -> dict[str, Any]:
    return list_tree(dataset.root, omit_job_dirs=True)


def dataset_file(dataset: OpenedDataset, relative: str) -> dict[str, Any]:
    return read_preview(dataset.root, relative, omit_job_dirs=True)


def list_plugins() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for plugin_id in BUILTIN_PLUGIN_IDS:
        root = _builtin_plugin_root(plugin_id)
        if root is None:
            continue
        try:
            manifest = load_manifest(root)
        except PluginManifestError:
            continue
        items.append(_plugin_row("builtin", manifest.plugin_id, manifest.version, manifest))
    for entry in load_plugin_index().plugins:
        root = resolve_plugin_root(entry)
        if not contained(plugins_root(), root):
            continue
        description = _plugin_description(root)
        items.append(
            {
                "source": "installed",
                "id": entry.plugin_id,
                "version": entry.version,
                "label": entry.plugin_id,
                "description": description,
                "read_only": True,
            }
        )
    return {"ok": True, "items": items}


def list_agents() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for row in builtin_harness_rows():
        harness_id = row["harness_id"]
        root = builtin_harness_root(harness_id)
        try:
            manifest = load_agent_manifest(root)
        except ConfigError:
            continue
        items.append(
            {
                "source": "builtin",
                "id": harness_id,
                "version": manifest.version,
                "label": row["label"] or harness_id,
                "description": manifest.description or row["description"],
                "read_only": True,
            }
        )
    for entry in load_agent_index(reconcile=False).agents:
        root = resolve_agent_root(entry)
        if not contained(agents_root(), root):
            continue
        items.append(
            {
                "source": "installed",
                "id": entry.agent_id,
                "version": entry.version,
                "label": entry.label or entry.agent_id,
                "description": _agent_description(root),
                "read_only": True,
            }
        )
    return {"ok": True, "items": items}


def plugin_package(source: str, plugin_id: str, version: str) -> dict[str, Any]:
    root, manifest = _plugin_root(source, plugin_id, version)
    description = manifest.description if manifest is not None else _plugin_description(root)
    resolved_id = manifest.plugin_id if manifest is not None else plugin_id
    resolved_version = manifest.version if manifest is not None else version
    payload = _package(
        kind="plugin",
        source=source,
        package_id=resolved_id,
        version=resolved_version,
        description=description,
        root=root,
        manifest_name="plugin.yaml",
    )
    payload["declared"] = _declared_slots(manifest)
    return payload


def agent_package(source: str, agent_id: str, version: str) -> dict[str, Any]:
    root = _agent_root(source, agent_id, version)
    description: str | None = None
    label = agent_id
    resolved_version = version
    try:
        manifest = load_agent_manifest(root)
    except ConfigError:
        manifest = None
    if manifest is not None:
        description = manifest.description
        label = manifest.label or agent_id
        resolved_version = manifest.version
    payload = _package(
        kind="agent",
        source=source,
        package_id=agent_id,
        version=resolved_version,
        description=description,
        root=root,
        manifest_name="agent.yaml",
    )
    payload["label"] = f"{label}@{resolved_version}"
    return payload


def plugin_tree(source: str, plugin_id: str, version: str) -> dict[str, Any]:
    root, _manifest = _plugin_root(source, plugin_id, version)
    return list_tree(root, omit_job_dirs=False)


def agent_tree(source: str, agent_id: str, version: str) -> dict[str, Any]:
    return list_tree(_agent_root(source, agent_id, version), omit_job_dirs=False)


def plugin_file(source: str, plugin_id: str, version: str, relative: str) -> dict[str, Any]:
    root, _manifest = _plugin_root(source, plugin_id, version)
    return read_preview(root, relative, omit_job_dirs=False)


def agent_file(source: str, agent_id: str, version: str, relative: str) -> dict[str, Any]:
    return read_preview(_agent_root(source, agent_id, version), relative, omit_job_dirs=False)


def _package(
    *,
    kind: str,
    source: str,
    package_id: str,
    version: str,
    description: str | None,
    root: Path,
    manifest_name: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "kind": kind,
        "source": source,
        "id": package_id,
        "version": version,
        "label": f"{package_id}@{version}",
        "description": description,
        "readme": _file_name(root, "README.md"),
        "manifest": _file_name(root, manifest_name),
        "profiles": _file_name(root, "profiles.yaml"),
        "read_only": True,
    }


def _declared_slots(manifest: PluginManifest | None) -> list[dict[str, Any]]:
    if manifest is None:
        return []
    rows: list[dict[str, Any]] = []
    for kind, entries in (("exclusive", manifest.exclusive), ("chain", manifest.chain)):
        for slot in entries:
            rows.append(
                {
                    "id": slot.id,
                    "kind": kind,
                    "entry": slot.entry,
                    "priority": slot.priority,
                }
            )
    return rows


def _plugin_row(
    source: str,
    plugin_id: str,
    version: str,
    manifest: PluginManifest | None,
) -> dict[str, Any]:
    return {
        "source": source,
        "id": plugin_id,
        "version": version,
        "label": plugin_id,
        "description": None if manifest is None else manifest.description,
        "read_only": True,
    }


def _plugin_root(source: str, plugin_id: str, version: str) -> tuple[Path, PluginManifest | None]:
    if source == "builtin":
        if plugin_id not in RESERVED_PLUGIN_IDS:
            _unknown(f"unknown builtin plugin {plugin_id}")
        root = _builtin_plugin_root(plugin_id)
        if root is None:
            _unknown(f"unknown builtin plugin {plugin_id}")
        try:
            manifest = load_manifest(root)
        except PluginManifestError as exc:
            raise ConfigError(ERROR_INVALID_PACKAGE, str(exc), location=plugin_id) from exc
        if manifest.version != version:
            _unknown(f"unknown builtin plugin version {version}")
        return root, manifest
    if source != "installed":
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            f"unknown plugin source {source}",
            location="source",
        )
    for entry in load_plugin_index().plugins:
        if entry.plugin_id == plugin_id and entry.version == version:
            root = resolve_plugin_root(entry)
            if not contained(plugins_root(), root) or not root.is_dir():
                _unknown(f"plugin package is not under the plugin index: {plugin_id}")
            try:
                manifest = load_manifest(root)
            except PluginManifestError:
                manifest = None
            return root, manifest
    _unknown(f"unknown installed plugin {plugin_id}@{version}")


def _agent_root(source: str, agent_id: str, version: str) -> Path:
    if source == "builtin":
        try:
            root = builtin_harness_root(agent_id)
        except ConfigError as exc:
            _unknown(str(exc))
        try:
            manifest: AgentManifest | None = load_agent_manifest(root)
        except ConfigError as exc:
            raise ConfigError(exc.error_code, str(exc), location=agent_id) from exc
        if manifest.version != version:
            _unknown(f"unknown builtin agent version {version}")
        return root
    if source != "installed":
        raise ConfigError(
            ERROR_INVALID_PACKAGE,
            f"unknown agent source {source}",
            location="source",
        )
    for entry in load_agent_index(reconcile=False).agents:
        if entry.agent_id == agent_id and entry.version == version:
            root = resolve_agent_root(entry)
            if not contained(agents_root(), root) or not root.is_dir():
                _unknown(f"agent package is not under the agent index: {agent_id}")
            return root
    _unknown(f"unknown installed agent {agent_id}@{version}")


def _builtin_plugin_root(plugin_id: str) -> Path | None:
    name = plugin_id.replace("-", "_")
    if not name.isidentifier():
        return None
    root = _CONTRIB / name
    if (root / "plugin.yaml").is_file():
        return root
    return None


def _plugin_description(root: Path) -> str | None:
    try:
        return load_manifest(root).description
    except PluginManifestError:
        return _yaml_description(root / "plugin.yaml")


def _agent_description(root: Path) -> str | None:
    try:
        return load_agent_manifest(root).description
    except ConfigError:
        return _yaml_description(root / "agent.yaml")


def _yaml_description(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(raw, dict):
        return None
    text = raw.get("description")
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    return stripped or None


def _file_name(root: Path, name: str) -> str | None:
    return name if (root / name).is_file() else None


def _unknown(message: str) -> NoReturn:
    raise ConfigError("unknown_package", message, location="package")
