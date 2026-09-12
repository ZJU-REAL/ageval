"""Hub catalog overlay for builtin agent harnesses. Not lock/run authority.

Reads ``src/ageval/agents/builtin/catalog.json`` and the sibling file tree.
Do not import ``ageval.plugins.contrib``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.registry.errors import RegistryAppError

from ageval.agents.reserved import (
    builtin_harness_ids,
    builtin_harness_root,
    builtin_harness_rows,
    canonical_harness_id,
    reserved_harness_leaf,
)

# Keep in lockstep with apps/hub/src/lib/brand-marks/harness.ts HARNESS_BRAND_MARK.
HARNESS_ICON_KEY = {
    "pi": "pi",
    "opencode": "opencode",
    "codex": "codex",
    "claude-code": "claude-code",
    "grok-build": "grok",
    "openai-http": "openai",
    "anthropic-http": "anthropic",
}


def is_builtin_agent_id(dataset_id: str) -> bool:
    return canonical_harness_id(dataset_id) is not None


def _iter_package_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise RegistryAppError("not_found", "builtin agent files missing", http_status=404)
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "catalog.json":
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        out.append(path)
    return out


def _overlay_item(row: dict[str, str]) -> dict[str, Any]:
    harness_id = row["harness_id"]
    root = builtin_harness_root(harness_id)
    files = [p.relative_to(root).as_posix() for p in _iter_package_files(root)]
    preview: dict[str, Any] = {
        "agent_id": harness_id,
        "format": "ageval.agent/1",
        "label": row["label"],
        "description": row["description"],
        "files": files[:200],
    }
    manifest = root / "agent.yaml"
    if manifest.is_file():
        from ageval.agents.manifest import load_agent_manifest

        man = load_agent_manifest(root)
        preview["format"] = "ageval.agent/1"
        preview["agent_id"] = man.agent_id
        preview["version"] = man.version
        if man.label:
            preview["label"] = man.label
        if man.description:
            preview["description"] = man.description
        if man.tags:
            preview["tags"] = list(man.tags)
        preview["binding"] = dict(man.binding)
    item: dict[str, Any] = {
        "dataset_id": harness_id,
        "package_kind": "agent",
        "visibility": "public",
        "builtin": True,
        "official": False,
        "display_name": str(preview.get("label") or row["label"]),
        "agent_preview": preview,
    }
    icon = HARNESS_ICON_KEY.get(harness_id)
    if icon:
        item["icon_key"] = icon
    return item


def builtin_list_files(dataset_id: str) -> dict[str, Any]:
    harness_id = canonical_harness_id(dataset_id)
    if harness_id is None:
        raise RegistryAppError("not_found", "builtin agent not found", http_status=404)
    root = builtin_harness_root(harness_id)
    items = [
        {
            "path": path.relative_to(root).as_posix(),
            "type": "file",
            "size": path.stat().st_size,
        }
        for path in _iter_package_files(root)
    ]
    return {"dataset_id": harness_id, "items": items}


def builtin_read_file(dataset_id: str, file_path: str) -> dict[str, Any]:
    from services.registry.package_files import (
        MAX_FILE_BYTES,
        PackagePathError,
        file_payload,
        normalize_package_path,
    )

    harness_id = canonical_harness_id(dataset_id)
    if harness_id is None:
        raise RegistryAppError("not_found", "builtin agent not found", http_status=404)
    try:
        safe_path = normalize_package_path(file_path)
    except PackagePathError as exc:
        raise RegistryAppError("invalid_path", str(exc), http_status=400) from exc
    root = builtin_harness_root(harness_id)
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


def builtin_agent_item(dataset_id: str) -> dict[str, Any] | None:
    key = canonical_harness_id(dataset_id)
    if key is None:
        return None
    for row in builtin_harness_rows():
        if row["harness_id"] == key:
            return _overlay_item(row)
    return None


def builtin_agent_items(*, prefix: str | None = None) -> list[dict[str, Any]]:
    needle = (prefix or "").strip().casefold()
    out: list[dict[str, Any]] = []
    for row in builtin_harness_rows():
        harness_id = row["harness_id"]
        if needle and not harness_id.casefold().startswith(needle):
            continue
        out.append(_overlay_item(row))
    return out


__all__ = [
    "builtin_agent_item",
    "builtin_agent_items",
    "builtin_harness_ids",
    "builtin_list_files",
    "builtin_read_file",
    "is_builtin_agent_id",
    "reserved_harness_leaf",
    "HARNESS_ICON_KEY",
]
