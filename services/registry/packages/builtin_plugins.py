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
_CONTRIB_ROOT = Path(__file__).resolve().parents[3] / "src" / "ageval" / "plugins" / "contrib"
_CONTRIB_DIR = {
    "local": "local",
    "docker": "docker",
    "e2b": "e2b",
    "ssh": "ssh",
    "daytona": "daytona",
    "acp": "acp",
    "openai-http": "openai_http",
    "anthropic-http": "anthropic_http",
}


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


def canonical_plugin_id(dataset_id: str) -> str | None:
    key = dataset_id.strip().casefold()
    if not key:
        return None
    for row in catalog_rows():
        if str(row["plugin_id"]).casefold() == key:
            return str(row["plugin_id"])
    return None


def contrib_package_root(plugin_id: str) -> Path:
    canonical = canonical_plugin_id(plugin_id) or plugin_id.strip()
    dirname = _CONTRIB_DIR.get(canonical, canonical)
    return _CONTRIB_ROOT / dirname


def _iter_package_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise RegistryAppError("not_found", "builtin plugin files missing", http_status=404)
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        out.append(path)
    return out


def _overlay_item(row: dict[str, Any]) -> dict[str, Any]:
    exclusive = list(row["exclusive"])
    chain = list(row["chain"])
    declared = [{"id": slot, "kind": "exclusive"} for slot in exclusive] + [
        {"id": slot, "kind": "chain"} for slot in chain
    ]
    root = contrib_package_root(str(row["plugin_id"]))
    files = [p.relative_to(root).as_posix() for p in _iter_package_files(root)]
    preview: dict[str, Any] = {
        "plugin_id": row["plugin_id"],
        "description": row["description"],
        "format": "ageval.plugin/1",
        "slots": {"exclusive": exclusive, "chain": chain},
        "declared": declared,
        "files": files[:200],
    }
    manifest = root / "plugin.yaml"
    if manifest.is_file():
        from ageval.plugins.manifest import load_manifest

        man = load_manifest(root)
        preview["format"] = man.format
        preview["version"] = man.version
        if man.description:
            preview["description"] = man.description
        declared = []
        for kind, entries in (("exclusive", man.exclusive), ("chain", man.chain)):
            for slot in entries:
                declared.append(
                    {
                        "id": slot.id,
                        "kind": kind,
                        "entry": slot.entry,
                        "priority": slot.priority,
                    }
                )
        preview["declared"] = declared
        preview["slots"] = man.slots_summary()
    item: dict[str, Any] = {
        "dataset_id": row["plugin_id"],
        "package_kind": "plugin",
        "visibility": "public",
        "builtin": True,
        "official": False,
        "plugin_preview": preview,
    }
    if row["host_requires"]:
        item["host_requires"] = list(row["host_requires"])
    return item


def builtin_list_files(dataset_id: str) -> dict[str, Any]:
    plugin_id = canonical_plugin_id(dataset_id)
    if plugin_id is None:
        raise RegistryAppError("not_found", "builtin plugin not found", http_status=404)
    root = contrib_package_root(plugin_id)
    items = [
        {
            "path": path.relative_to(root).as_posix(),
            "type": "file",
            "size": path.stat().st_size,
        }
        for path in _iter_package_files(root)
    ]
    return {"dataset_id": plugin_id, "items": items}


def builtin_read_file(dataset_id: str, file_path: str) -> dict[str, Any]:
    from services.registry.content.files import (
        MAX_FILE_BYTES,
        PackagePathError,
        file_payload,
        normalize_package_path,
    )

    plugin_id = canonical_plugin_id(dataset_id)
    if plugin_id is None:
        raise RegistryAppError("not_found", "builtin plugin not found", http_status=404)
    try:
        safe_path = normalize_package_path(file_path)
    except PackagePathError as exc:
        raise RegistryAppError("invalid_path", str(exc), http_status=400) from exc
    root = contrib_package_root(plugin_id)
    target = (root / safe_path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise RegistryAppError(
            "invalid_path",
            "path escapes package root",
            http_status=400,
        ) from exc
    if not target.is_file():
        raise RegistryAppError("not_found", f"file not found: {safe_path}", http_status=404)
    size = target.stat().st_size
    data = target.read_bytes()[:MAX_FILE_BYTES]
    truncated = size > MAX_FILE_BYTES
    return file_payload(safe_path, data, size=size, truncated=truncated)


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
