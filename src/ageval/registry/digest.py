"""Suite packageDigest: sorted paths + per-file sha256 + outer sha256.

Algorithm (Spec 21 Phase 0 freeze):

1. Enumerate files via ``member_paths_for_digest`` (stable order; includes root
   ``ageval.yaml``, optional ``shared/**``, files named by binding ``overlays:``,
   and every non-hidden member file except ``__pycache__`` / ``*.pyc``).
2. For each path, compute ``sha256`` of raw file bytes.
3. Build canonical text (UTF-8, LF only)::

       <hex64>  <posix-relative-path>\\n

4. ``packageDigest = "sha256:" + sha256(canonical_text).hexdigest()``.

Paths are package-relative posix strings; no host absolute paths enter the digest.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ageval.config.dataset import member_paths_for_digest


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_package_digest(dataset_root: Path) -> str:
    """Return ``sha256:<64 hex>`` over the canonical package tree."""
    root = dataset_root.expanduser().resolve(strict=False)
    lines: list[str] = []
    for rel in member_paths_for_digest(root):
        abs_path = root / rel
        if not abs_path.is_file():
            continue
        digest = file_sha256(abs_path)
        lines.append(f"{digest}  {rel}\n")
    blob = "".join(lines).encode("utf-8")
    return f"sha256:{hashlib.sha256(blob).hexdigest()}"


_DESCRIPTIVE_MANIFEST_KEYS = frozenset({"description"})


def _eval_member_file(root: Path, file_path: Path) -> str | None:
    if not file_path.is_file():
        return None
    if "__pycache__" in file_path.parts or file_path.name.endswith(".pyc"):
        return None
    if file_path.name.startswith("."):
        return None
    try:
        return file_path.relative_to(root).as_posix()
    except ValueError:
        return None


def compute_eval_digest(dataset_root: Path) -> str:
    """Digest over files that affect scoring only (design/12).

    Covers the root manifest minus descriptive fields, every file under each
    task member and under dataset-level ``shared/``, plus the declarative
    ``assets`` manifest / ``prepare`` script when present (both live in or are
    named by ``ageval.yaml``, so manifest hashing already covers the manifest;
    the prepare script body is hashed explicitly). README, LICENSE and other
    root docs are excluded, so docs-only edits keep the digest.
    """
    import yaml

    from ageval.config.dataset import list_tasks, load_dataset_manifest
    from ageval.config.digest import canonical_json_bytes

    root = dataset_root.expanduser().resolve(strict=False)
    man = load_dataset_manifest(root)
    lines: list[str] = []

    raw_manifest = yaml.safe_load((root / "ageval.yaml").read_text(encoding="utf-8")) or {}
    if isinstance(raw_manifest, dict):
        scrubbed = {
            k: v for k, v in raw_manifest.items() if k not in _DESCRIPTIVE_MANIFEST_KEYS
        }
        assets = scrubbed.get("assets")
        if isinstance(assets, list):
            scrubbed["assets"] = [
                {"path": a.get("path"), "sha256": a.get("sha256")}
                if isinstance(a, dict)
                else a
                for a in assets
            ]
    else:  # pragma: no cover - load_dataset_manifest already rejects this
        scrubbed = {}
    manifest_hash = hashlib.sha256(canonical_json_bytes(scrubbed)).hexdigest()
    lines.append(f"{manifest_hash}  ageval.yaml\n")

    rels: set[str] = set()
    shared_dir = root / "shared"
    if shared_dir.is_dir():
        for file_path in sorted(shared_dir.rglob("*")):
            rel = _eval_member_file(root, file_path)
            if rel is not None:
                rels.add(rel)
    for tid in list_tasks(root, manifest=man):
        task_dir = root / man.tasks_root / tid
        for file_path in sorted(task_dir.rglob("*")):
            rel = _eval_member_file(root, file_path)
            if rel is not None:
                rels.add(rel)
    prepare_rel = getattr(man, "prepare", None)
    if prepare_rel:
        rel = str(prepare_rel).replace("\\", "/").removeprefix("./")
        if (root / rel).is_file():
            rels.add(rel)
    for rel in sorted(rels):
        lines.append(f"{file_sha256(root / rel)}  {rel}\n")
    blob = "".join(lines).encode("utf-8")
    return f"sha256:{hashlib.sha256(blob).hexdigest()}"
