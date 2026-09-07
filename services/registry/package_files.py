"""Package archive file tree index + single-member read (#38 / Hub S2).

Server-side only: never ship whole archive to the browser for preview.
Index is keyed by package digest (immutable). Path rules reject traversal.
"""

from __future__ import annotations

import gzip
import io
import re
import tarfile
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

# Hub / Config overlay source: root ``profiles.yaml`` plus ``profiles*.yaml``
# anywhere except ``tasks/`` (basename ``profiles`` or ``profiles.*``).
_PROFILES_BASENAME = re.compile(r"^profiles(\.|$)")
_OVERLAY_ITEM = re.compile(r"""^\s*-\s+["']?(overlays/\S+?)["']?\s*$""")

# Hard cap for single-file body (Hub preview). Oversize → HTTP 413.
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB

DATASET_MANIFEST_PATH = "ageval.yaml"


def _dataset_description(text: str) -> str:
    """`/description` from the dataset root manifest (`ageval.dataset/1`)."""
    import yaml

    from ageval.config.dataset import DATASET_FORMAT

    doc = yaml.safe_load(text)
    if not isinstance(doc, dict) or doc.get("format") != DATASET_FORMAT:
        return ""
    desc = doc.get("description")
    return desc.strip() if isinstance(desc, str) else ""


# Process-local LRU of tar member indexes by package_digest.
_INDEX_LRU_MAX = 64
_index_lock = threading.Lock()
_index_lru: OrderedDict[str, PackageFileIndex] = OrderedDict()


class PackagePathError(ValueError):
    """Invalid or unsafe package-relative path."""


class PackageFileNotFound(LookupError):
    """Path not present in archive."""


class PackageFileTooLarge(ValueError):
    """Member exceeds MAX_FILE_BYTES."""

    def __init__(self, path: str, size: int) -> None:
        self.path = path
        self.size = size
        super().__init__(f"file too large: {path} ({size} bytes > {MAX_FILE_BYTES})")


def is_profiles_document(path: str) -> bool:
    """True for Hub overlay-source yaml (not task trees)."""
    if not path.endswith(".yaml"):
        return False
    if path.startswith("tasks/"):
        return False
    name = path.rsplit("/", 1)[-1]
    return bool(_PROFILES_BASENAME.match(name))


def overlay_paths_from_profiles_yaml(text: str) -> list[str]:
    """Best-effort ``- overlays/…`` list items from a profiles yaml."""
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = _OVERLAY_ITEM.match(line)
        if not match:
            continue
        item = match.group(1)
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def normalize_package_path(raw: str) -> str:
    """Normalize and validate a package-relative path.

    Rejects absolute paths, ``..``, empty segments, and backslashes.
    """
    text = (raw or "").strip()
    if not text:
        raise PackagePathError("empty path")
    if text.startswith("/") or text.startswith("\\"):
        raise PackagePathError("absolute path not allowed")
    # Windows-style drive or UNC
    if len(text) >= 2 and text[1] == ":":
        raise PackagePathError("absolute path not allowed")
    if "\\" in text:
        raise PackagePathError("backslash not allowed")
    parts = text.split("/")
    if any(p == "" or p == "." or p == ".." for p in parts):
        raise PackagePathError("invalid path segment")
    return "/".join(parts)


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str
    type: str  # "file" | "dir"
    size: int


@dataclass
class PackageFileIndex:
    package_digest: str
    entries: list[FileEntry]
    # path → (size, is_dir) for O(1) lookup; files only store size
    _by_path: dict[str, FileEntry]
    overlay_prefixes: list[str] = field(default_factory=list)
    description: str = ""

    def list_items(self) -> list[dict[str, Any]]:
        return [
            {"path": e.path, "type": e.type, "size": e.size}
            for e in sorted(self.entries, key=lambda x: x.path)
        ]

    def get(self, path: str) -> FileEntry | None:
        return self._by_path.get(path)

    def list_tasks(self) -> tuple[list[dict[str, Any]], bool]:
        """Return ``(task rows, has_shared)`` from the archive index.

        Each row is ``{task_id, has_readme}``, sorted by task_id.
        """
        readme: dict[str, bool] = {}
        has_shared = False
        for entry in self.entries:
            path = entry.path
            if path == "shared" or path.startswith("shared/"):
                has_shared = True
            if not path.startswith("tasks/"):
                continue
            rest = path[len("tasks/") :]
            if not rest:
                continue
            task_id = rest.split("/", 1)[0]
            if not task_id:
                continue
            if task_id not in readme:
                readme[task_id] = False
            if entry.type == "file" and rest == f"{task_id}/README.md":
                readme[task_id] = True
        items = [{"task_id": task_id, "has_readme": readme[task_id]} for task_id in sorted(readme)]
        return items, has_shared


def build_index_from_archive(archive: bytes, *, package_digest: str) -> PackageFileIndex:
    """List tar members (gzip-compressed package archive)."""
    entries: list[FileEntry] = []
    by_path: dict[str, FileEntry] = {}
    overlay_prefixes: list[str] = []
    overlay_seen: set[str] = set()
    description = ""
    with (
        gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb") as gz,
        tarfile.open(fileobj=gz, mode="r:") as tar,
    ):
        for info in tar.getmembers():
            name = info.name
            if not name or name.endswith("/"):
                # directory member may have trailing slash
                path = name.rstrip("/")
            else:
                path = name
            if not path or path.startswith("/") or ".." in path.split("/"):
                continue
            if info.isdir():
                entry = FileEntry(path=path, type="dir", size=0)
            elif info.isfile():
                entry = FileEntry(path=path, type="file", size=int(info.size))
                if path == DATASET_MANIFEST_PATH and not description:
                    handle = tar.extractfile(info)
                    if handle is not None:
                        description = _dataset_description(
                            handle.read(MAX_FILE_BYTES).decode("utf-8")
                        )
                if is_profiles_document(path):
                    handle = tar.extractfile(info)
                    if handle is not None:
                        try:
                            text = handle.read(MAX_FILE_BYTES).decode("utf-8")
                        except UnicodeDecodeError:
                            text = ""
                        for item in overlay_paths_from_profiles_yaml(text):
                            if item in overlay_seen:
                                continue
                            overlay_seen.add(item)
                            overlay_prefixes.append(item)
            else:
                continue
            # Prefer first occurrence; skip duplicates
            if path in by_path:
                continue
            by_path[path] = entry
            entries.append(entry)
            # Ensure parent dirs are listed even if tar omitted dir headers
            parts = path.split("/")
            for i in range(1, len(parts)):
                d = "/".join(parts[:i])
                if d not in by_path:
                    d_entry = FileEntry(path=d, type="dir", size=0)
                    by_path[d] = d_entry
                    entries.append(d_entry)
    return PackageFileIndex(
        package_digest=package_digest,
        entries=entries,
        _by_path=by_path,
        overlay_prefixes=overlay_prefixes,
        description=description,
    )


def get_or_build_index(archive: bytes, *, package_digest: str) -> PackageFileIndex:
    with _index_lock:
        if package_digest in _index_lru:
            _index_lru.move_to_end(package_digest)
            return _index_lru[package_digest]
    index = build_index_from_archive(archive, package_digest=package_digest)
    with _index_lock:
        _index_lru[package_digest] = index
        _index_lru.move_to_end(package_digest)
        while len(_index_lru) > _INDEX_LRU_MAX:
            _index_lru.popitem(last=False)
    return index


def clear_index_cache() -> None:
    """Test helper."""
    with _index_lock:
        _index_lru.clear()


def read_member(
    archive: bytes,
    path: str,
    *,
    max_bytes: int = MAX_FILE_BYTES,
    allow_truncate: bool = True,
) -> tuple[bytes, int, bool]:
    """Return ``(content, full_size, truncated)`` for a file member.

    When *allow_truncate* is True (Hub preview default), oversize members return
    the first *max_bytes* with ``truncated=True`` instead of failing closed.
    Set *allow_truncate* False to raise :class:`PackageFileTooLarge`.

    Raises
    ------
    PackagePathError
        Unsafe path.
    PackageFileNotFound
        Missing or directory.
    PackageFileTooLarge
        Size exceeds *max_bytes* and *allow_truncate* is False.
    """
    safe = normalize_package_path(path)
    with (
        gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb") as gz,
        tarfile.open(fileobj=gz, mode="r:") as tar,
    ):
        try:
            info = tar.getmember(safe)
        except KeyError as exc:
            # Some archives may store with trailing slash for dirs only
            raise PackageFileNotFound(safe) from exc
        if info.isdir():
            raise PackageFileNotFound(safe)
        if not info.isfile():
            raise PackageFileNotFound(safe)
        size = int(info.size)
        if size > max_bytes and not allow_truncate:
            raise PackageFileTooLarge(safe, size)
        f = tar.extractfile(info)
        if f is None:
            raise PackageFileNotFound(safe)
        # Read at most max_bytes for preview; full size still reported via *size*.
        data = f.read(max_bytes)
        truncated = size > len(data)
        if truncated and not allow_truncate:
            raise PackageFileTooLarge(safe, size)
        # Avoid cutting mid UTF-8 code unit so Hub can show text previews.
        if truncated and data:
            for drop in range(0, min(4, len(data))):
                chunk = data if drop == 0 else data[:-drop]
                try:
                    chunk.decode("utf-8")
                    data = chunk
                    break
                except UnicodeDecodeError:
                    continue
        return data, size, truncated


def content_type_for_path(path: str) -> str:
    lower = path.lower()
    if lower.endswith((".json", ".lock")):
        return "application/json; charset=utf-8"
    if lower.endswith((".yaml", ".yml")):
        return "text/yaml; charset=utf-8"
    if lower.endswith((".md", ".markdown", ".txt", ".py", ".sh", ".toml", ".cfg", ".ini")):
        return "text/plain; charset=utf-8"
    if lower.endswith((".html", ".htm")):
        return "text/html; charset=utf-8"
    if lower.endswith((".css",)):
        return "text/css; charset=utf-8"
    if lower.endswith((".js", ".mjs", ".ts", ".tsx")):
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def file_payload(
    path: str,
    data: bytes,
    *,
    size: int,
    truncated: bool = False,
) -> dict[str, Any]:
    """JSON envelope for file content (UTF-8 text or base64)."""
    try:
        text = data.decode("utf-8")
        # Reject if too many NULs (likely binary)
        if "\x00" in text:
            raise UnicodeDecodeError("utf-8", data, 0, 1, "nul")
        return {
            "path": path,
            "size": size,
            "encoding": "utf-8",
            "content": text,
            "truncated": truncated,
        }
    except UnicodeDecodeError:
        import base64

        return {
            "path": path,
            "size": size,
            "encoding": "base64",
            "content": base64.b64encode(data).decode("ascii"),
            "truncated": truncated,
        }
