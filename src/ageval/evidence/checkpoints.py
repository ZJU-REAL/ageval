"""Content-addressed workspace, home, and artifacts checkpoints.

``local`` and ``docker`` scan the host bind root. Remote kinds upload a delta
into the same layout. Settled Attempts drop ``checkpoints/`` unless the run
asked to keep the workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from ageval.config.errors import ERROR_INVALID_FORMAT, ConfigError
from ageval.evidence.store import CHECKPOINTS_DIR_REL

CHECKPOINT_FORMAT = "ageval.checkpoint/1"


def _invalid(message: str) -> NoReturn:
    raise ValueError(message)


def _bad_type(message: str) -> NoReturn:
    raise TypeError(message)


_ROOTS = ("workspace", "home", "artifacts")

# Credential files copied by keyless auth. Never enter ``blobs/``.
DEFAULT_EXCLUDED_RELS = frozenset(
    {
        "home/.codex/auth.json",
        "home/.claude/.credentials.json",
        "home/.pi/agent/auth.json",
        "home/.local/share/opencode/auth.json",
        "home/.grok/auth.json",
    }
)


def exclude_keyless_rels(home_rels: Iterable[str]) -> frozenset[str]:
    """Map ``keyless_auth_paths`` (home-relative) onto checkpoint rel paths."""
    out = set(DEFAULT_EXCLUDED_RELS)
    for rel in home_rels:
        text = str(rel).strip().lstrip("/")
        if text:
            out.add(f"home/{text}")
    return frozenset(out)


def prune_checkpoints(attempt_dir: Path) -> None:
    """Remove the checkpoint store after ``result.json`` is sealed."""
    root = attempt_dir / CHECKPOINTS_DIR_REL
    if root.is_dir():
        shutil.rmtree(root)


def prune_recovery_state(attempt_dir: Path) -> None:
    """Remove ``<attempt>/state`` once the Attempt is settled.

    ``local`` and ``docker`` also delete this directory in ``stop(delete=True)``.
    Remote kinds leave the host copy beside ``box/`` until seal.
    """
    root = attempt_dir / "state"
    if root.is_dir():
        shutil.rmtree(root)


class CheckpointStore:
    """Incremental snapshots of one Attempt box."""

    def __init__(
        self,
        attempt_dir: Path,
        box_dir: Path,
        *,
        exclude: Iterable[str] = (),
        sentinels: Iterable[str] = (),
    ) -> None:
        self.attempt_dir = attempt_dir
        self.box_dir = box_dir
        self.root = attempt_dir / CHECKPOINTS_DIR_REL
        self.exclude = set(DEFAULT_EXCLUDED_RELS)
        self.exclude.update(str(item) for item in exclude if str(item).strip())
        self.sentinels = tuple(item for item in sentinels if item)
        self.redaction_notes: list[str] = []
        self._cache: dict[str, tuple[int, int, str]] = {}

    def capture(self, seq: int) -> Path:
        """Write ``seq_<NNNNNN>.json`` and any new blobs. Return the manifest path."""
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            _invalid(f"checkpoint seq must be a positive int, got {seq!r}")
        self.redaction_notes = []
        entries: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        for rel, path in _iter_files(self.box_dir):
            if rel in self.exclude or _excluded(rel, self.exclude):
                continue
            try:
                payload = self._checkpoint_bytes(rel, path)
                if payload is None:
                    continue
                stat = path.stat()
            except FileNotFoundError:
                # The agent can delete a home file (sqlite sidecars, staging
                # dirs) between the walk and the read. It is not part of this seq.
                continue
            seen.add(rel)
            cached = self._cache.get(rel)
            if cached is not None and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
                digest = cached[2]
            else:
                digest = hashlib.sha256(payload).hexdigest()
                self._cache[rel] = (stat.st_mtime_ns, stat.st_size, digest)
                _write_blob_bytes(self.root, digest, payload)
            entries[rel] = {
                "kind": "file",
                "mode": stat.st_mode & 0o777,
                "size": len(payload),
                "mtime_ns": stat.st_mtime_ns,
                "sha256": digest,
            }
        self._cache = {key: value for key, value in self._cache.items() if key in seen}
        manifest = {
            "format": CHECKPOINT_FORMAT,
            "seq": seq,
            "created_at": _utc_now(),
            "entries": dict(sorted(entries.items())),
        }
        path = self.manifest_path(seq)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, manifest)
        return path

    def _checkpoint_bytes(self, rel: str, path: Path) -> bytes | None:
        """Bytes to store. Home text is redacted. A secret in a binary home file is omitted."""
        raw = path.read_bytes()
        if not rel.startswith("home/"):
            return raw
        if _looks_binary(raw):
            if _binary_has_secret(raw, self.sentinels):
                self.redaction_notes.append(rel)
                return None
            return raw
        text = raw.decode("utf-8")
        from ageval.evidence.redaction import redact_text

        cleaned = redact_text(text, extra_sentinels=self.sentinels)
        return cleaned.encode("utf-8")

    def manifest_path(self, seq: int) -> Path:
        return self.root / f"seq_{seq:06d}.json"

    def restore(self, seq: int, *, dest: Path | None = None) -> None:
        """Make ``dest`` (default: the capture box) match manifest ``seq``."""
        path = self.manifest_path(seq)
        manifest = _read_manifest(path)
        if manifest.get("seq") != seq:
            _invalid(f"checkpoint {path.name} seq is {manifest.get('seq')}, expected {seq}")
        entries = manifest.get("entries")
        if not isinstance(entries, dict):
            _bad_type(f"checkpoint {path.name} entries must be an object")
        target = dest if dest is not None else self.box_dir
        wanted: set[str] = set()
        for rel, meta in entries.items():
            if not isinstance(rel, str) or not isinstance(meta, dict):
                _invalid(f"checkpoint entry {rel!r} is invalid")
            if _excluded(rel, self.exclude) or rel in self.exclude:
                continue
            digest = meta.get("sha256")
            if not isinstance(digest, str) or len(digest) != 64:
                _invalid(f"checkpoint entry {rel} has no sha256")
            blob = self.root / "blobs" / digest[:2] / digest
            if not blob.is_file():
                _invalid(f"checkpoint blob missing for {rel}")
            dest_path = _safe_rel(target, rel)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(blob, dest_path)
            mode = meta.get("mode")
            if isinstance(mode, int) and not isinstance(mode, bool):
                os.chmod(dest_path, mode & 0o777)
            mtime = meta.get("mtime_ns")
            if isinstance(mtime, int) and not isinstance(mtime, bool):
                os.utime(dest_path, ns=(mtime, mtime))
            wanted.add(rel)
        for rel, path_on_disk in _iter_files(target):
            if rel in wanted or rel in self.exclude or _excluded(rel, self.exclude):
                continue
            path_on_disk.unlink()
        _prune_empty_dirs(target)


def _utc_now() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _excluded(rel: str, exclude: set[str]) -> bool:
    return rel in exclude


def _iter_files(box: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for prefix in _ROOTS:
        base = box / prefix
        if not base.is_dir() or base.is_symlink():
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            current = Path(dirpath)
            dirnames[:] = sorted(name for name in dirnames if not (current / name).is_symlink())
            for name in sorted(filenames):
                path = current / name
                if path.is_symlink() or not path.is_file():
                    continue
                rel = f"{prefix}/{path.relative_to(base).as_posix()}"
                found.append((rel, path))
    return found


def _looks_binary(raw: bytes) -> bool:
    sample = raw[:8192]
    return b"\x00" in sample


def _binary_has_secret(raw: bytes, sentinels: tuple[str, ...]) -> bool:
    from ageval.evidence.redaction import scan_for_secrets

    text = raw.decode("latin-1")
    return bool(scan_for_secrets(text, extra_sentinels=sentinels))


def _write_blob_bytes(root: Path, digest: str, payload: bytes) -> None:
    dest = root / "blobs" / digest[:2] / digest
    if dest.is_file():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_bytes(payload)
    os.replace(tmp, dest)


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    raw = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    tmp.write_text(raw, encoding="utf-8")
    with tmp.open("a", encoding="utf-8") as handle:
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        _invalid(f"checkpoint manifest missing: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        _bad_type(f"checkpoint {path.name} is not an object")
    if data.get("format") != CHECKPOINT_FORMAT:
        msg = f"checkpoint format must be {CHECKPOINT_FORMAT}"
        raise ConfigError(ERROR_INVALID_FORMAT, msg, location="/format")
    return data


def _safe_rel(root: Path, rel: str) -> Path:
    if not rel or rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        _invalid(f"checkpoint path rejected: {rel}")
    parts = Path(rel).parts
    if not parts or parts[0] not in _ROOTS:
        _invalid(f"checkpoint path is outside the box roots: {rel}")
    return root.joinpath(*parts)


def _prune_empty_dirs(box: Path) -> None:
    for prefix in _ROOTS:
        base = box / prefix
        if not base.is_dir():
            continue
        for dirpath, _dirnames, _filenames in os.walk(base, topdown=False):
            current = Path(dirpath)
            if current == base or not current.is_dir():
                continue
            if not any(current.iterdir()):
                current.rmdir()
