"""Dataset-level preparation: declarative assets + gated prepare script.

Runs between resolving a Dataset and opening any Attempt (design/02).
Assets are fetched only when missing or digest-mismatched and are always
sha256-verified; the optional ``prepare`` script is disabled by default and
runs only with explicit allowance or a trusted Dataset. Scripts stay as
trusted as Dockerfiles — the gate is about consent, not sandboxing.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from ageval.config.dataset import DatasetAsset, load_dataset_manifest
from ageval.config.errors import ConfigError

ERROR_ASSET_DOWNLOAD_FAILED = "asset_download_failed"
ERROR_ASSET_DIGEST_MISMATCH = "asset_digest_mismatch"
ERROR_PREPARE_NOT_ALLOWED = "prepare_not_allowed"
ERROR_PREPARE_FAILED = "prepare_failed"

TRUST_ENV = "AGEVAL_PREPARE_TRUST"
DEFAULT_PREPARE_TIMEOUT_SECONDS = 600


@dataclass(frozen=True, slots=True)
class PrepareReport:
    downloaded: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    prepare_ran: bool = False
    prepare_script: str | None = None

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "downloaded": list(self.downloaded),
            "skipped": list(self.skipped),
            "prepare_ran": self.prepare_ran,
        }
        if self.prepare_script:
            out["prepare"] = self.prepare_script
        return out


@dataclass(slots=True)
class _Acc:
    downloaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_trusted_dataset(dataset_id: str, root: Path) -> bool:
    """Trust list: ``AGEVAL_PREPARE_TRUST`` holds dataset_ids or root paths."""
    from ageval.config.env_refs import prepare_trust_entries

    entries = prepare_trust_entries()
    return dataset_id in entries or str(root) in entries


def _download(asset: DatasetAsset, dest_dir: Path) -> Path:
    tmp = Path(tempfile.mktemp(prefix=".ageval-asset-", dir=str(dest_dir)))
    try:
        if asset.url.startswith("file://"):
            src = Path(unquote(urlparse(asset.url).path))
            shutil.copyfile(src, tmp)
        else:
            req = urllib.request.Request(asset.url, headers={"User-Agent": "ageval"})
            with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:  # noqa: S310
                shutil.copyfileobj(resp, out)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        tmp.unlink(missing_ok=True)
        raise ConfigError(
            ERROR_ASSET_DOWNLOAD_FAILED,
            f"cannot download asset {asset.path} from {asset.url}: {exc}",
            location=asset.path,
        ) from exc
    return tmp


def _ensure_asset(root: Path, asset: DatasetAsset, acc: _Acc) -> None:
    dest = root / asset.path
    if dest.is_file() and file_sha256(dest) == asset.sha256:
        acc.skipped.append(asset.path)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = _download(asset, dest.parent)
    try:
        got = file_sha256(tmp)
        if got != asset.sha256:
            raise ConfigError(
                ERROR_ASSET_DIGEST_MISMATCH,
                f"asset {asset.path} sha256 mismatch: expected {asset.sha256}, got {got}",
                location=asset.path,
            )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    acc.downloaded.append(asset.path)


def _run_prepare_script(root: Path, script_rel: str, *, timeout: int) -> None:
    script = root / script_rel
    if not script.is_file():
        raise ConfigError(
            ERROR_PREPARE_FAILED, f"prepare script not found: {script_rel}", location="/prepare"
        )
    text = script.read_text(encoding="utf-8", errors="replace")
    if ".." in Path(script_rel).parts or "../" in text or "..\\" in text:
        raise ConfigError(
            ERROR_PREPARE_FAILED,
            "prepare script must not reference paths outside the dataset root",
            location="/prepare",
        )
    from ageval.config.env_refs import prepare_script_env

    try:
        proc = subprocess.run(
            ["/bin/sh", script_rel],
            cwd=str(root),
            env=prepare_script_env(str(root)),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConfigError(
            ERROR_PREPARE_FAILED,
            f"prepare script timed out after {timeout}s",
            location="/prepare",
        ) from exc
    except OSError as exc:
        raise ConfigError(
            ERROR_PREPARE_FAILED, f"cannot run prepare script: {exc}", location="/prepare"
        ) from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = tail[-1] if tail else f"exit {proc.returncode}"
        raise ConfigError(
            ERROR_PREPARE_FAILED, f"prepare script failed: {detail}", location="/prepare"
        )


PREPARE_MARKER = ".ageval-prepare.json"


def _prepare_key(root: Path, manifest: object) -> str:
    import json

    assets = [{"path": a.path, "sha256": a.sha256} for a in getattr(manifest, "assets", ())]
    script = getattr(manifest, "prepare", None)
    script_hash = ""
    if script and (root / script).is_file():
        script_hash = file_sha256(root / script)
    payload = json.dumps(
        {"prepare": script, "script_sha256": script_hash, "assets": assets},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _prepare_marker_matches(root: Path, manifest: object) -> bool:
    import json

    marker = root / PREPARE_MARKER
    if not marker.is_file():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("key") == _prepare_key(root, manifest)


def _marker_data(root: Path) -> dict[str, object] | None:
    import json

    marker = root / PREPARE_MARKER
    if not marker.is_file():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def stored_eval_digest(root: Path) -> str | None:
    """Digest recorded when the prepare script first ran, when still valid.

    Prepare output stays on disk, so recomputing over the working tree on a
    later lock would drift. The marker pins the pre-prepare digest while
    the script + assets key is unchanged.
    """
    manifest = load_dataset_manifest(root)
    if not manifest.prepare:
        return None
    data = _marker_data(root)
    if data is None or data.get("key") != _prepare_key(root, manifest):
        return None
    digest = data.get("eval_digest")
    return digest if isinstance(digest, str) and digest.startswith("sha256:") else None


def _write_prepare_marker(root: Path, manifest: object, eval_digest: str | None = None) -> None:
    import json

    payload: dict[str, object] = {
        "key": _prepare_key(root, manifest),
        "dataset_id": getattr(manifest, "dataset_id", ""),
    }
    if eval_digest:
        payload["eval_digest"] = eval_digest
    (root / PREPARE_MARKER).write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def prepare_dataset(
    dataset_root: Path,
    *,
    allow_prepare: bool = False,
    trusted: bool = False,
    timeout: int = DEFAULT_PREPARE_TIMEOUT_SECONDS,
    on_prepare_script: Callable[[str, str], None] | None = None,
    eval_digest: str | None = None,
) -> PrepareReport:
    """Fetch declared assets and, when allowed, run the prepare script.

    Stops before any Attempt opens on download failure, digest mismatch,
    or an unapproved prepare script.
    """
    root = dataset_root.expanduser().resolve(strict=False)
    manifest = load_dataset_manifest(root)
    # The gate comes first: an unapproved dataset downloads nothing.
    if manifest.prepare:
        allowed = allow_prepare or trusted or is_trusted_dataset(manifest.dataset_id, root)
        if not allowed:
            raise ConfigError(
                ERROR_PREPARE_NOT_ALLOWED,
                "dataset declares a prepare script; rerun with --allow-prepare "
                f"or add {manifest.dataset_id} to {TRUST_ENV}",
                location="/prepare",
            )
    acc = _Acc()
    for asset in manifest.assets:
        _ensure_asset(root, asset, acc)
    prepare_ran = False
    if manifest.prepare:
        if not _prepare_marker_matches(root, manifest):
            if callable(on_prepare_script):
                on_prepare_script(manifest.prepare, manifest.dataset_id)
            _run_prepare_script(root, manifest.prepare, timeout=timeout)
            prepare_ran = True
        # Declared assets are still sha256-verified after the script runs.
        for asset in manifest.assets:
            dest = root / asset.path
            if not dest.is_file() or file_sha256(dest) != asset.sha256:
                raise ConfigError(
                    ERROR_ASSET_DIGEST_MISMATCH,
                    f"asset {asset.path} missing or sha256 mismatch after prepare",
                    location=asset.path,
                )
        if prepare_ran:
            _write_prepare_marker(root, manifest, eval_digest=eval_digest)
    return PrepareReport(
        downloaded=tuple(acc.downloaded),
        skipped=tuple(acc.skipped),
        prepare_ran=prepare_ran,
        prepare_script=manifest.prepare,
    )
