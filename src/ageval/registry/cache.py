"""Atomic verified Dataset cache under ``.ageval/cache/datasets/``."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from ageval.registry.archive import extract_archive
from ageval.registry.digest import compute_package_digest


def default_cache_root() -> Path:
    env = os.environ.get("AGEVAL_CACHE_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.cwd() / ".ageval" / "cache").resolve()


GIT_SOURCE_MARKER = ".ageval-git-source.json"


class PackageCache:
    """Filesystem cache: ``<root>/datasets/<id>/<packageDigest>/``."""

    def __init__(self, cache_root: Path | None = None) -> None:
        self.root = (cache_root or default_cache_root()).resolve()

    def entry_dir(self, dataset_id: str, package_digest: str) -> Path:
        # dataset_id may contain '/'; encode as nested path is fine (validated charset).
        digest_key = package_digest.replace(":", "_")
        return self.root / "datasets" / dataset_id / digest_key

    def lookup(self, dataset_id: str, package_digest: str) -> Path | None:
        """Return verified cache path or None if missing/corrupt."""
        entry = self.entry_dir(dataset_id, package_digest)
        marker = entry / ".ageval-verified"
        if not marker.is_file():
            return None
        try:
            meta = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if meta.get("package_digest") != package_digest:
            return None
        if not (entry / "ageval.yaml").is_file():
            return None
        # Re-hash on lookup is optional; v1 trusts marker + present root after write-time verify.
        return entry

    def lookup_version(self, dataset_id: str, version: str) -> Path | None:
        """Return the unique verified cache root for ``dataset_id@version``.

        Used so ``ageval view official/demo@0.1.0`` can open a prior fetch
        without contacting the registry. Several matching digests → None
        (caller falls through to Hub or a digest ref).
        """
        from ageval.config.dataset import load_dataset_manifest
        from ageval.config.errors import ConfigError

        want_id = str(dataset_id or "").strip()
        want_ver = str(version or "").strip()
        if not want_id or not want_ver:
            return None
        matches: list[Path] = []
        for entry in self._iter_verified():
            try:
                man = load_dataset_manifest(entry)
            except (ConfigError, OSError, UnicodeDecodeError):
                continue
            if man.dataset_id == want_id and man.version == want_ver:
                matches.append(entry)
        if len(matches) == 1:
            return matches[0]
        return None

    def _iter_verified(self) -> list[Path]:
        base = self.root / "datasets"
        if not base.is_dir():
            return []
        rows: list[Path] = []
        for marker in sorted(base.rglob(".ageval-verified")):
            entry = marker.parent
            if (entry / "ageval.yaml").is_file():
                rows.append(entry)
        return rows

    def publish_atomic(
        self,
        *,
        dataset_id: str,
        package_digest: str,
        archive: Path,
        expected_blob_digest: str | None = None,
    ) -> Path:
        """Extract archive into a temp dir, verify packageDigest, then atomic rename."""
        import hashlib

        if expected_blob_digest is not None:
            digest = hashlib.sha256()
            with archive.open("rb") as fh:
                while True:
                    block = fh.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
            actual = f"sha256:{digest.hexdigest()}"
            if actual != expected_blob_digest:
                msg = f"blob digest mismatch: expected {expected_blob_digest}, got {actual}"
                raise ValueError(msg)

        final = self.entry_dir(dataset_id, package_digest)
        if self.lookup(dataset_id, package_digest) is not None:
            return final

        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=".ageval-cache-tmp-", dir=str(final.parent)))
        try:
            extract_archive(archive, tmp)
            got = compute_package_digest(tmp)
            if got != package_digest:
                msg = f"package digest mismatch after extract: expected {package_digest}, got {got}"
                raise ValueError(msg)
            marker = {
                "package_digest": package_digest,
                "dataset_id": dataset_id,
                "schema": "ageval.cache.verified/1",
            }
            (tmp / ".ageval-verified").write_text(
                json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8"
            )
            # Atomic publish: rename temp → final (replace if partial exists).
            if final.exists():
                shutil.rmtree(final)
            tmp.rename(final)
            return final
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    # --- git sources -------------------------------------------------------

    def git_entry_dir(self, git_url: str, commit: str, subdir: str | None) -> Path:
        import hashlib

        url_key = hashlib.sha256(git_url.encode("utf-8")).hexdigest()[:24]
        sub_key = hashlib.sha256((subdir or "").encode("utf-8")).hexdigest()[:16]
        return self.root / "git" / url_key / commit / sub_key

    def lookup_git(
        self, git_url: str, commit: str, subdir: str | None
    ) -> Path | None:
        entry = self.git_entry_dir(git_url, commit, subdir)
        marker = entry / GIT_SOURCE_MARKER
        if not marker.is_file() or not (entry / "ageval.yaml").is_file():
            return None
        try:
            meta = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if meta.get("git_url") != git_url or meta.get("commit") != commit:
            return None
        if (meta.get("subdir") or None) != (subdir or None):
            return None
        return entry

    def publish_git(
        self,
        *,
        git_url: str,
        commit: str,
        git_ref: str,
        subdir: str | None,
        source_root: Path,
    ) -> Path:
        """Copy a checked-out Dataset tree into the git cache atomically."""
        final = self.git_entry_dir(git_url, commit, subdir)
        hit = self.lookup_git(git_url, commit, subdir)
        if hit is not None:
            return hit
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=".ageval-git-tmp-", dir=str(final.parent)))
        try:
            shutil.copytree(
                source_root,
                tmp,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".git"),
            )
            marker = {
                "schema": "ageval.git-source/1",
                "git_url": git_url,
                "commit": commit,
                "git_ref": git_ref,
                "subdir": subdir,
            }
            (tmp / GIT_SOURCE_MARKER).write_text(
                json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8"
            )
            if final.exists():
                shutil.rmtree(final)
            tmp.rename(final)
            return final
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
