"""Dockerfile fragments bound plugins contribute to an Attempt image.

A layer list is not a slot. Nothing runs at a point in the timeline here: the
environment winner reads what the bound plugins declared and folds it into the
image it builds. That is why ``image_contribute`` left the timeline.

Installed Hub packages come from the plugin index. First-party contribs
(``src/ageval/plugins/contrib/``) are resolved from this checkout / wheel.
ACP's layer body is the bound ``options.entry`` so the docker content key
changes when the entry changes and not when only ``model`` does.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ageval.plugins.manifest import PluginManifest, load_manifest
from ageval.plugins.store import load_index, resolve_package_root

if TYPE_CHECKING:
    from ageval.plugins.protocol import ExtensionGraph

_CONTRIB_ROOT = Path(__file__).resolve().parent / "contrib"


@dataclass(frozen=True, slots=True)
class ImageLayer:
    """One plugin's bake file, built with the plugin package as context."""

    plugin_id: str
    dockerfile: Path
    package_root: Path
    body: str


def layers_for_plugins(plugin_ids: frozenset[str]) -> tuple[ImageLayer, ...]:
    """Bake files declared by the bound plugins among *plugin_ids*.

    Ordered by plugin id so the image key does not depend on resolve order.
    """
    if not plugin_ids:
        return ()
    found: list[ImageLayer] = []
    for plugin_id in sorted(plugin_ids):
        root, resolved_id = _package_root(plugin_id)
        if root is None:
            continue
        manifest = _manifest(root)
        if manifest is None or manifest.image_layers is None:
            continue
        fragment = root / manifest.image_layers
        if not fragment.is_file():
            continue
        found.append(
            ImageLayer(
                plugin_id=resolved_id,
                dockerfile=fragment,
                package_root=root,
                body=fragment.read_text("utf-8"),
            )
        )
    return tuple(found)


def _package_root(plugin_id: str) -> tuple[Path | None, str]:
    """Installed package root, else first-party contrib next to this module."""
    entry = load_index().find(plugin_id)
    if entry is not None:
        return resolve_package_root(entry), entry.plugin_id
    bundled = _bundled_contrib_root(plugin_id)
    if bundled is None:
        return None, plugin_id
    return bundled, plugin_id


def _bundled_contrib_root(plugin_id: str) -> Path | None:
    name = plugin_id.replace("-", "_")
    if not name.isidentifier():
        return None
    root = _CONTRIB_ROOT / name
    if (root / "plugin.yaml").is_file():
        return root
    return None


def _manifest(root: Path) -> PluginManifest | None:
    from ageval.plugins.manifest import PluginManifestError

    try:
        return load_manifest(root)
    except PluginManifestError:
        # A broken install is reported where it is installed, not here.
        return None


def graph_plugin_ids(graph: ExtensionGraph) -> frozenset[str]:
    """Plugin ids a graph binds: exclusive winners plus every chain handler."""
    bound = {ref.plugin_id for ref in graph.winners.values()}
    for chain in graph.chains.values():
        bound.update(handler.plugin_id for handler in chain)
    return frozenset(bound)


def graph_plugin_options(graph: ExtensionGraph) -> dict[str, dict[str, Any]]:
    """Per-plugin options on a graph (exclusive winner, then chain handlers)."""
    found: dict[str, dict[str, Any]] = {}
    for winner in graph.winners.values():
        if winner.options:
            found[winner.plugin_id] = dict(winner.options)
    for handlers in graph.chains.values():
        for handler in handlers:
            if handler.options:
                found[handler.plugin_id] = {
                    **found.get(handler.plugin_id, {}),
                    **dict(handler.options),
                }
    return found


def _apply_bound_options(
    layers: Iterable[ImageLayer],
    options_by_plugin: Mapping[str, Mapping[str, Any]],
) -> tuple[ImageLayer, ...]:
    """Fill ACP's bake body with the bound ``options.entry`` pins."""
    from ageval.plugins.contrib.acp.bake import render_bake_body
    from ageval.plugins.contrib.acp.options import AcpOptions
    from ageval.plugins.options import coerce_options

    out: list[ImageLayer] = []
    for layer in layers:
        if layer.plugin_id != "acp":
            out.append(layer)
            continue
        entry = coerce_options(AcpOptions, options_by_plugin.get("acp") or {}).entry
        out.append(
            ImageLayer(
                plugin_id=layer.plugin_id,
                dockerfile=layer.dockerfile,
                package_root=layer.package_root,
                body=render_bake_body(layer.body, entry),
            )
        )
    return tuple(out)


def layers_tuple(layers: Iterable[ImageLayer]) -> tuple[tuple[str, str, str, str], ...]:
    """The factory-facing layer shape (plugin_id, dockerfile, package_root, body)."""
    return tuple(
        (layer.plugin_id, str(layer.dockerfile), str(layer.package_root), layer.body)
        for layer in layers
    )


def layers_for_graph(graph: ExtensionGraph) -> tuple[tuple[str, str, str, str], ...]:
    """Bake files declared by the plugins one graph binds, for kinds that build."""
    options = graph_plugin_options(graph)
    layers = _apply_bound_options(layers_for_plugins(graph_plugin_ids(graph)), options)
    return layers_tuple(layers)


def layers_for_graphs(
    graphs: Iterable[ExtensionGraph],
) -> tuple[tuple[str, str, str, str], ...]:
    """Union bake files over several graphs, ordered by plugin id."""
    bound: set[str] = set()
    options: dict[str, dict[str, Any]] = {}
    for graph in graphs:
        bound.update(graph_plugin_ids(graph))
        for plugin_id, opts in graph_plugin_options(graph).items():
            options[plugin_id] = {**options.get(plugin_id, {}), **dict(opts)}
    layers = _apply_bound_options(layers_for_plugins(frozenset(bound)), options)
    return layers_tuple(layers)
