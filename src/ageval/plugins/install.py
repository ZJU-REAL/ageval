"""Transitive ``ageval plugin install`` (plugin_requires first, then the request)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ageval.plugins.host_requires import installed_plugin
from ageval.plugins.manifest import (
    PluginManifestError,
    load_manifest,
    split_plugin_id,
)
from ageval.plugins.plugin_requires import PluginRequiresError, assert_no_plugin_requires_cycle
from ageval.plugins.reserved import reject_reserved_plugin_id
from ageval.plugins.store import IndexEntry, install_from_path, load_index

HubFetch = Callable[[str], Path]


@dataclass
class InstalledItem:
    plugin_id: str
    version: str
    digest: str
    path: str
    status: str  # installed | already_present


@dataclass
class InstallResult:
    entry: IndexEntry
    items: list[InstalledItem] = field(default_factory=list)

    def as_cli_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "plugin_id": self.entry.plugin_id,
            "version": self.entry.version,
            "digest": self.entry.digest,
            "path": self.entry.path,
            "slots_summary": self.entry.slots_summary,
            "installed": [
                {
                    "digest": item.digest,
                    "plugin_id": item.plugin_id,
                    "status": item.status,
                    "version": item.version,
                }
                for item in self.items
            ],
        }


def install_from_local(source: Path, *, hub_fetch: HubFetch | None = None) -> InstallResult:
    """Install a local plugin directory and its ``plugin_requires``."""
    root = source.expanduser().resolve(strict=False)
    manifest = load_manifest(root)
    reject_reserved_plugin_id(manifest.plugin_id)
    return _install_tree(
        root,
        index_id=manifest.plugin_id,
        source_kind="local",
        stack=(),
        hub_fetch=hub_fetch,
    )


def install_extracted_hub(
    source: Path,
    *,
    plugin_id: str,
    hub_fetch: HubFetch | None = None,
) -> InstallResult:
    """Install an extracted Hub tree under the exact ``org/name`` cache id."""
    reject_reserved_plugin_id(plugin_id)
    root = source.expanduser().resolve(strict=False)
    return _install_tree(
        root,
        index_id=plugin_id,
        source_kind="hub",
        stack=(),
        hub_fetch=hub_fetch,
    )


def _install_tree(
    source: Path,
    *,
    index_id: str,
    source_kind: str,
    stack: tuple[str, ...],
    hub_fetch: HubFetch | None,
) -> InstallResult:
    if index_id in stack:
        chain = " -> ".join((*stack, index_id))
        raise PluginRequiresError(
            f"plugin_requires cycle: {chain}",
            kind="plugin_requires_cycle",
        )
    manifest = load_manifest(source)
    nxt = (*stack, index_id)
    items: list[InstalledItem] = []
    seen: set[str] = set()
    for req in manifest.plugin_requires:
        dep = _resolve_require(
            req.plugin_id,
            source=source,
            source_kind=source_kind,
            stack=nxt,
            hub_fetch=hub_fetch,
            hint=req.hint,
        )
        for item in dep.items:
            if item.plugin_id in seen:
                continue
            seen.add(item.plugin_id)
            items.append(item)
    prior = load_index().find(index_id)
    entry = install_from_path(source, plugin_id=index_id)
    same_digest = prior is not None and prior.digest == entry.digest
    status = "already_present" if same_digest else "installed"
    if index_id not in seen:
        items.append(
            InstalledItem(
                plugin_id=entry.plugin_id,
                version=entry.version,
                digest=entry.digest,
                path=entry.path,
                status=status,
            )
        )
    return InstallResult(entry=entry, items=items)


def _resolve_require(
    plugin_id: str,
    *,
    source: Path,
    source_kind: str,
    stack: tuple[str, ...],
    hub_fetch: HubFetch | None,
    hint: str | None,
) -> InstallResult:
    if plugin_id in stack:
        chain = " -> ".join((*stack, plugin_id))
        raise PluginRequiresError(
            f"plugin_requires cycle: {chain}",
            kind="plugin_requires_cycle",
        )
    cached = load_index().find(plugin_id)
    if cached is not None:
        assert_no_plugin_requires_cycle(plugin_id, stack=stack)
        return InstallResult(entry=cached, items=[_item_from_entry(cached, "already_present")])

    org, name = split_plugin_id(plugin_id)
    if org is None:
        if source_kind != "local":
            raise _unsatisfied(plugin_id, hint, "short plugin_id is not in cache (no Hub guess)")
        sibling = source.parent / name
        if not sibling.is_dir():
            raise _unsatisfied(plugin_id, hint, f"sibling missing: {sibling.name}")
        try:
            sibling_manifest = load_manifest(sibling)
        except PluginManifestError as exc:
            raise _unsatisfied(plugin_id, hint, f"sibling is not a plugin: {exc.message}") from exc
        if sibling_manifest.plugin_id != name:
            raise _unsatisfied(
                plugin_id,
                hint,
                f"sibling plugin_id is {sibling_manifest.plugin_id!r}, want {name!r}",
            )
        return _install_tree(
            sibling,
            index_id=name,
            source_kind="local",
            stack=stack,
            hub_fetch=hub_fetch,
        )

    if hub_fetch is None:
        raise _unsatisfied(plugin_id, hint, "Hub locator requires a registry fetch")
    extracted = hub_fetch(plugin_id)
    return _install_tree(
        extracted,
        index_id=plugin_id,
        source_kind="hub",
        stack=stack,
        hub_fetch=hub_fetch,
    )


def _item_from_entry(entry: IndexEntry, status: str) -> InstalledItem:
    return InstalledItem(
        plugin_id=entry.plugin_id,
        version=entry.version,
        digest=entry.digest,
        path=entry.path,
        status=status,
    )


def _unsatisfied(plugin_id: str, hint: str | None, detail: str) -> PluginRequiresError:
    suffix = f" ({hint})" if hint else ""
    return PluginRequiresError(
        f"plugin_requires {plugin_id!r} unsatisfied: {detail}{suffix}",
        kind="plugin_requires_unsatisfied",
    )


def required_package_roots(plugin_id: str) -> list[Path]:
    """Installed package roots for *plugin_id* and its requires (cycle-safe)."""
    roots: list[Path] = []
    seen: set[str] = set()

    def walk(pid: str, stack: tuple[str, ...]) -> None:
        if pid in stack:
            chain = " -> ".join((*stack, pid))
            raise PluginRequiresError(
                f"plugin_requires cycle: {chain}",
                kind="plugin_requires_cycle",
            )
        if pid in seen:
            return
        found = installed_plugin(pid)
        if found is None:
            return
        seen.add(pid)
        _manifest, root = found
        roots.append(root)
        for item in _manifest.plugin_requires:
            walk(item.plugin_id, (*stack, pid))

    walk(plugin_id, ())
    return roots
