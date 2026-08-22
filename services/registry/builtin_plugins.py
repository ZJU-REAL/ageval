"""Hub catalog overlay for first-party contrib. Not lock/run authority.

Registry reads ``builtin_plugins.json``. Do not import ``ageval.plugins.contrib``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.registry.errors import RegistryAppError

_PATH = Path(__file__).with_name("builtin_plugins.json")
_ROW_KEYS = frozenset({"plugin_id", "description", "host_requires", "exclusive", "chain"})


def _load_rows() -> tuple[dict[str, Any], ...]:
    raw = json.loads(_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise RegistryAppError("invalid_format", "builtin plugin catalog is empty", http_status=500)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != _ROW_KEYS:
            raise RegistryAppError(
                "invalid_format",
                "builtin catalog row keys: plugin_id, description, host_requires, exclusive, chain",
                http_status=500,
            )
        plugin_id = item["plugin_id"]
        if not isinstance(plugin_id, str) or not plugin_id.strip() or "/" in plugin_id:
            raise RegistryAppError(
                "invalid_format", "builtin plugin_id must be a short id", http_status=500
            )
        key = plugin_id.strip()
        if key in seen:
            raise RegistryAppError(
                "invalid_format", f"duplicate builtin plugin_id {key!r}", http_status=500
            )
        seen.add(key)
        description = item["description"]
        if not isinstance(description, str) or not description.strip():
            raise RegistryAppError(
                "invalid_format",
                f"builtin {key!r} description required",
                http_status=500,
            )
        host_requires = item["host_requires"]
        exclusive = item["exclusive"]
        chain = item["chain"]
        if not isinstance(host_requires, list) or not all(
            isinstance(x, str) for x in host_requires
        ):
            raise RegistryAppError(
                "invalid_format",
                f"builtin {key!r} host_requires must be a list of strings",
                http_status=500,
            )
        if not isinstance(exclusive, list) or not all(isinstance(x, str) and x for x in exclusive):
            raise RegistryAppError(
                "invalid_format",
                f"builtin {key!r} exclusive must be a list of slot ids",
                http_status=500,
            )
        if not isinstance(chain, list) or not all(isinstance(x, str) and x for x in chain):
            raise RegistryAppError(
                "invalid_format",
                f"builtin {key!r} chain must be a list of slot ids",
                http_status=500,
            )
        rows.append(
            {
                "plugin_id": key,
                "description": description.strip(),
                "host_requires": [h.strip() for h in host_requires if h.strip()],
                "exclusive": list(exclusive),
                "chain": list(chain),
            }
        )
    return tuple(rows)


_ROWS: tuple[dict[str, Any], ...] | None = None


def catalog_rows() -> tuple[dict[str, Any], ...]:
    global _ROWS
    if _ROWS is None:
        _ROWS = _load_rows()
    return _ROWS


def builtin_plugin_ids() -> frozenset[str]:
    return frozenset(row["plugin_id"] for row in catalog_rows())


def is_builtin_plugin_id(dataset_id: str) -> bool:
    key = dataset_id.strip().casefold()
    if not key:
        return False
    return any(str(row["plugin_id"]).casefold() == key for row in catalog_rows())


def _overlay_item(row: dict[str, Any]) -> dict[str, Any]:
    exclusive = list(row["exclusive"])
    chain = list(row["chain"])
    declared = [{"id": slot, "kind": "exclusive"} for slot in exclusive] + [
        {"id": slot, "kind": "chain"} for slot in chain
    ]
    item: dict[str, Any] = {
        "dataset_id": row["plugin_id"],
        "package_kind": "plugin",
        "visibility": "public",
        "builtin": True,
        "official": False,
        "plugin_preview": {
            "plugin_id": row["plugin_id"],
            "description": row["description"],
            "slots": {"exclusive": exclusive, "chain": chain},
            "declared": declared,
        },
    }
    if row["host_requires"]:
        item["host_requires"] = list(row["host_requires"])
    return item


def builtin_plugin_item(dataset_id: str) -> dict[str, Any] | None:
    key = dataset_id.strip().casefold()
    if not key:
        return None
    for row in catalog_rows():
        if str(row["plugin_id"]).casefold() == key:
            return _overlay_item(row)
    return None


def builtin_plugin_items(*, prefix: str | None = None) -> list[dict[str, Any]]:
    needle = (prefix or "").strip().casefold()
    out: list[dict[str, Any]] = []
    for row in catalog_rows():
        plugin_id = str(row["plugin_id"])
        if needle and not plugin_id.casefold().startswith(needle):
            continue
        out.append(_overlay_item(row))
    return out
