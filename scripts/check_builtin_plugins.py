#!/usr/bin/env python3
"""Fail if Hub builtin catalog drifts from first-party contrib registrations.

Builds an empty ExtensionRegistry and calls only register_*_contrib.
Does not call bootstrap_registry / load_installed_plugins.

Run: uv run python scripts/check_builtin_plugins.py
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "services/registry/builtin_plugins.json"
ROW_KEYS = frozenset({"plugin_id", "description", "host_requires", "exclusive", "chain"})


def _fail(message: str) -> int:
    print(f"check_builtin_plugins: {message}", file=sys.stderr)
    return 1


def _contrib_register_fns() -> list[object]:
    import ageval.plugins.contrib as contrib_pkg

    fns: list[object] = []
    for info in pkgutil.iter_modules(contrib_pkg.__path__):
        mod = importlib.import_module(f"{contrib_pkg.__name__}.{info.name}")
        for attr in dir(mod):
            if attr.startswith("register_") and attr.endswith("_contrib"):
                fns.append(getattr(mod, attr))
    return fns


def _slots_by_plugin(registry: Any) -> dict[str, dict[str, list[str]]]:
    from ageval.plugins.slots import ALL_SLOTS, SlotKind, get_slot_kind

    out: dict[str, dict[str, list[str]]] = {}
    for slot in ALL_SLOTS:
        kind = "exclusive" if get_slot_kind(slot) is SlotKind.EXCLUSIVE else "chain"
        for plugin_id in registry.plugins_for_slot(slot):
            row = out.setdefault(plugin_id, {"exclusive": [], "chain": []})
            row[kind].append(slot)
    return out


def main() -> int:
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        return _fail("catalog must be a nonempty JSON list")

    catalog_ids: set[str] = set()
    catalog_slots: dict[str, dict[str, list[str]]] = {}
    for item in raw:
        if not isinstance(item, dict) or set(item) != ROW_KEYS:
            return _fail(
                "each row keys must be plugin_id, description, host_requires, exclusive, chain"
            )
        plugin_id = item["plugin_id"]
        if not isinstance(plugin_id, str) or not plugin_id or "/" in plugin_id:
            return _fail(f"invalid plugin_id {plugin_id!r}")
        if plugin_id in catalog_ids:
            return _fail(f"duplicate plugin_id {plugin_id!r}")
        catalog_ids.add(plugin_id)
        exclusive = item["exclusive"]
        chain = item["chain"]
        if not isinstance(exclusive, list) or not all(isinstance(x, str) for x in exclusive):
            return _fail(f"{plugin_id}: exclusive must be a list of strings")
        if not isinstance(chain, list) or not all(isinstance(x, str) for x in chain):
            return _fail(f"{plugin_id}: chain must be a list of strings")
        catalog_slots[plugin_id] = {"exclusive": list(exclusive), "chain": list(chain)}

    from ageval.plugins.registry import ExtensionRegistry
    from ageval.plugins.reserved import RESERVED_PLUGIN_IDS

    registry = ExtensionRegistry()
    for fn in _contrib_register_fns():
        fn(registry)
    contrib_slots = _slots_by_plugin(registry)
    contrib_ids = set(contrib_slots)

    if contrib_ids != catalog_ids:
        missing = sorted(contrib_ids - catalog_ids)
        extra = sorted(catalog_ids - contrib_ids)
        return _fail(f"plugin_id set mismatch; missing={missing} extra={extra}")
    if contrib_ids != set(RESERVED_PLUGIN_IDS):
        return _fail(f"reserved ids {sorted(RESERVED_PLUGIN_IDS)} != contrib {sorted(contrib_ids)}")

    for plugin_id, want in catalog_slots.items():
        got = contrib_slots[plugin_id]
        if sorted(want["exclusive"]) != sorted(got["exclusive"]) or sorted(want["chain"]) != sorted(
            got["chain"]
        ):
            return _fail(f"{plugin_id} slots drifted: catalog={want} contrib={got}")
    print(f"check_builtin_plugins: ok ({len(catalog_ids)} contrib ids)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
