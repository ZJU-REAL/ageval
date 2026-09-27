"""One-shot suite snapshot shares.

Creates a capability URL. Does not write suite visibility, result_shares,
or board_listed.
"""

from __future__ import annotations

import gzip
import io
import json
import secrets
import tarfile
from pathlib import Path
from typing import Any

from services.registry.blob_io import read_blob, sha256_file
from services.registry.errors import RegistryAppError
from services.registry.rows import SnapshotShareRow
from services.registry.store import TokenInfo, now

from ageval.evidence.locators import run_locator, suite_run_locator
from ageval.registry.media_types import SHARE_SNAPSHOT_MEDIA_TYPE
from ageval.registry.share_snapshot import (
    SHARE_BLOB_PREFIX,
    SNAPSHOT_SHARE_KIND,
    archive_contains_snapshot_marker,
    archive_member_names,
    read_archive_member,
    snapshot_has_plaintext_secret,
)

_META_KEYS = frozenset(
    {"suite_run_id", "dataset_id", "dataset_version", "blob_digest", "size", "kind"}
)
_ACL_KEYS = frozenset({"visibility", "result_shares", "board_listed"})
_NOTE = "snapshot share; per-task evaluator verdicts only; no suite-level PASS"


def _require_str(meta: dict[str, Any], key: str) -> str:
    value = meta.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RegistryAppError(
            "invalid_request",
            f"{key} is required",
            http_status=400,
        )
    return value.strip()


class ShareService:
    def __init__(self, results: Any, blobs: Any, *, max_upload: int) -> None:
        self.results = results
        self.blobs = blobs
        self.max_upload = max_upload

    def create(self, *, meta: dict[str, Any], archive: Path, auth: TokenInfo) -> dict[str, Any]:
        if not auth.user_id:
            raise RegistryAppError(
                "unauthorized",
                "upload requires authenticated user identity",
                http_status=401,
            )
        forbidden = _ACL_KEYS & set(meta)
        if forbidden:
            raise RegistryAppError(
                "invalid_request",
                "snapshot share does not accept catalog ACL fields",
                http_status=400,
            )
        unknown = set(meta) - _META_KEYS
        if unknown:
            raise RegistryAppError(
                "invalid_request",
                "unknown keys: " + ", ".join(sorted(unknown)),
                http_status=400,
            )
        kind = meta.get("kind")
        if kind is not None and kind != SNAPSHOT_SHARE_KIND:
            raise RegistryAppError(
                "invalid_request",
                "kind must be snapshot-share",
                http_status=400,
            )
        suite_run_id = _require_str(meta, "suite_run_id")
        dataset_id = _require_str(meta, "dataset_id")
        dataset_version = _require_str(meta, "dataset_version")
        blob_digest = _require_str(meta, "blob_digest")
        size_on_disk = archive.stat().st_size
        if size_on_disk > self.max_upload:
            raise RegistryAppError(
                "payload_too_large",
                f"max {self.max_upload} bytes",
                http_status=413,
            )
        try:
            size = int(meta.get("size") or size_on_disk)
        except (TypeError, ValueError) as exc:
            raise RegistryAppError(
                "invalid_request", "size must be an integer", http_status=400
            ) from exc
        if sha256_file(archive) != blob_digest or size != size_on_disk:
            raise RegistryAppError(
                "digest_mismatch",
                "blob digest or size mismatch",
                http_status=400,
            )
        if not archive_contains_snapshot_marker(archive):
            raise RegistryAppError(
                "invalid_request",
                "snapshot-share.json is required",
                http_status=400,
            )
        if snapshot_has_plaintext_secret(archive):
            raise RegistryAppError(
                "secret_scan_failed",
                "snapshot contains a plaintext secret",
                http_status=400,
            )
        summary = self._summary_from_archive(
            archive,
            suite_run_id=suite_run_id,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
        )
        token = secrets.token_urlsafe(32)
        row = SnapshotShareRow(
            token=token,
            owner_user_id=auth.user_id,
            suite_run_id=suite_run_id,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            blob_digest=blob_digest,
            size=size,
            summary_json=json.dumps(summary, sort_keys=True),
            created_at=now(),
        )
        self.blobs.put_if_absent(blob_digest, archive, prefix=SHARE_BLOB_PREFIX)
        try:
            self.results.insert_snapshot_share(row)
        except ValueError as exc:
            raise RegistryAppError(
                "conflict",
                "snapshot share token collision",
                http_status=409,
            ) from exc
        return self._public(row)

    def get(self, token: str) -> dict[str, Any]:
        return self._public(self._require(token))

    def revoke(self, token: str, *, auth: TokenInfo) -> dict[str, Any]:
        row = self._require(token)
        if not auth.user_id or auth.user_id != row.owner_user_id:
            raise RegistryAppError(
                "forbidden",
                "snapshot share owner required",
                http_status=403,
            )
        self.results.delete_snapshot_share(token)
        if self.results.count_snapshot_share_blob_refs(row.blob_digest) == 0:
            self.blobs.delete(row.blob_digest, prefix=SHARE_BLOB_PREFIX)
        return {"ok": True, "token": token}

    def attempt_meta(self, token: str, run_id: str) -> dict[str, Any]:
        row = self._require(token)
        summary = json.loads(row.summary_json)
        hit = _ref_for_run(summary, run_id)
        if hit is None and not self._run_has_files(row, run_id):
            raise RegistryAppError("not_found", "attempt not in snapshot", http_status=404)
        payload: dict[str, Any] = {
            "run_id": run_id,
            "task_id": str((hit or {}).get("task_id") or ""),
            "dataset_id": row.dataset_id,
            "dataset_version": row.dataset_version,
            "suite_run_id": row.suite_run_id,
            "status": (hit or {}).get("status") or "",
            "score": (hit or {}).get("score"),
            "error": (hit or {}).get("error"),
            "limit": (hit or {}).get("limit"),
        }
        return payload

    def list_attempt_files(self, token: str, run_id: str) -> dict[str, Any]:
        row = self._require(token)
        self.attempt_meta(token, run_id)
        archive = self._archive_bytes(row)
        from services.registry.package_files import get_or_build_index

        index = get_or_build_index(archive, package_digest=row.blob_digest)
        prefix = run_locator(run_id)
        items = [
            item
            for item in index.list_items()
            if item["path"] == prefix or str(item["path"]).startswith(prefix + "/")
        ]
        return {
            "run_id": run_id,
            "dataset_id": row.dataset_id,
            "digest": row.blob_digest,
            "items": items,
        }

    def read_attempt_file(self, token: str, run_id: str, file_path: str) -> dict[str, Any]:
        from services.registry.package_files import (
            MAX_FILE_BYTES,
            PackageFileNotFound,
            PackageFileTooLarge,
            PackagePathError,
            file_payload,
            normalize_package_path,
            read_member,
        )

        row = self._require(token)
        try:
            safe_path = normalize_package_path(file_path)
        except PackagePathError as exc:
            raise RegistryAppError("invalid_path", str(exc), http_status=400) from exc
        prefix = run_locator(run_id)
        if safe_path != prefix and not safe_path.startswith(prefix + "/"):
            raise RegistryAppError("not_found", "file not found", http_status=404)
        archive = self._archive_bytes(row)
        try:
            data, size, truncated = read_member(
                archive, safe_path, max_bytes=MAX_FILE_BYTES, allow_truncate=True
            )
        except PackagePathError as exc:
            raise RegistryAppError("invalid_path", str(exc), http_status=400) from exc
        except PackageFileNotFound as exc:
            raise RegistryAppError(
                "not_found", f"file not found: {safe_path}", http_status=404
            ) from exc
        except PackageFileTooLarge as exc:
            raise RegistryAppError(
                "file_too_large",
                str(exc),
                http_status=413,
            ) from exc
        return file_payload(safe_path, data, size=size, truncated=truncated)

    def _require(self, token: str) -> SnapshotShareRow:
        row = self.results.get_snapshot_share(token)
        if row is None:
            raise RegistryAppError("not_found", "snapshot share not found", http_status=404)
        return row

    def _archive_bytes(self, row: SnapshotShareRow) -> bytes:
        archive = read_blob(self.blobs, row.blob_digest, prefix=SHARE_BLOB_PREFIX)
        if archive is None:
            raise RegistryAppError("not_found", "blob missing", http_status=404)
        return archive

    def _run_has_files(self, row: SnapshotShareRow, run_id: str) -> bool:
        prefix = run_locator(run_id) + "/"
        raw = self._archive_bytes(row)
        try:
            with (
                gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as gz,
                tarfile.open(fileobj=gz, mode="r:") as tar,
            ):
                return any(
                    (info.name[2:] if info.name.startswith("./") else info.name).startswith(prefix)
                    for info in tar.getmembers()
                )
        except (OSError, tarfile.TarError, gzip.BadGzipFile, EOFError):
            return False

    def _summary_from_archive(
        self,
        archive: Path,
        *,
        suite_run_id: str,
        dataset_id: str,
        dataset_version: str,
    ) -> dict[str, Any]:
        member = f"{suite_run_locator(suite_run_id)}/summary.json"
        raw = read_archive_member(archive, member)
        if raw is None:
            raise RegistryAppError(
                "invalid_request",
                "suite summary.json is missing from the snapshot",
                http_status=400,
            )
        try:
            summary = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RegistryAppError(
                "invalid_request",
                "suite summary.json is not JSON",
                http_status=400,
            ) from exc
        if not isinstance(summary, dict):
            raise RegistryAppError(
                "invalid_request",
                "suite summary.json must be an object",
                http_status=400,
            )
        if str(summary.get("dataset_id") or "") != dataset_id:
            raise RegistryAppError(
                "invalid_request",
                "dataset_id does not match summary.json",
                http_status=400,
            )
        if str(summary.get("dataset_version") or "") != dataset_version:
            raise RegistryAppError(
                "invalid_request",
                "dataset_version does not match summary.json",
                http_status=400,
            )
        if summary.get("suite_run_id") and str(summary.get("suite_run_id")) != suite_run_id:
            raise RegistryAppError(
                "invalid_request",
                "suite_run_id does not match summary.json",
                http_status=400,
            )
        names = set(archive_member_names(archive))
        refs = summary.get("task_refs")
        if isinstance(refs, list):
            stamped: list[Any] = []
            for ref in refs:
                if not isinstance(ref, dict):
                    stamped.append(ref)
                    continue
                item = dict(ref)
                run_id = str(item.get("run_id") or "").strip()
                prefix = f"{run_locator(run_id)}/" if run_id else ""
                item["has_attempt_content"] = bool(prefix) and any(
                    name.startswith(prefix) for name in names
                )
                stamped.append(item)
            summary["task_refs"] = stamped
        return summary

    def _public(self, row: SnapshotShareRow) -> dict[str, Any]:
        summary = json.loads(row.summary_json)
        if not isinstance(summary, dict):
            summary = {}
        raw_metrics = summary.get("metrics")
        metrics: dict[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}
        payload: dict[str, Any] = {
            "token": row.token,
            "path": f"/s/{row.token}",
            "kind": SNAPSHOT_SHARE_KIND,
            "media_type": SHARE_SNAPSHOT_MEDIA_TYPE,
            "suite_run_id": row.suite_run_id,
            "dataset_id": row.dataset_id,
            "dataset_version": row.dataset_version,
            "created_at": row.created_at,
            "blob_digest": row.blob_digest,
            "size": row.size,
            "pass_rate": summary.get("pass_rate", metrics.get("pass_rate")),
            "mean_score": summary.get("mean_score", metrics.get("mean_score")),
            "metrics": metrics,
            "task_refs": summary.get("task_refs")
            if isinstance(summary.get("task_refs"), list)
            else [],
            "agent_label": str(summary.get("agent_label") or ""),
            "model_label": str(summary.get("model_label") or ""),
            "exit_code": summary.get("exit_code", 0),
            "note": _NOTE,
        }
        for key in (
            "job_overlay",
            "actors_summary",
            "plugins",
            "config_fingerprint",
            "config_homogeneous",
        ):
            if key in summary:
                payload[key] = summary[key]
        return payload


def _ref_for_run(summary: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    refs = summary.get("task_refs")
    if not isinstance(refs, list):
        return None
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        ids = [str(ref.get("run_id") or "").strip()]
        extra = ref.get("attempt_run_ids")
        if isinstance(extra, list):
            ids.extend(str(item).strip() for item in extra if item)
        previous = ref.get("previous")
        if isinstance(previous, list):
            for item in previous:
                if isinstance(item, dict) and item.get("run_id"):
                    ids.append(str(item["run_id"]).strip())
        if run_id in ids:
            return ref
    return None
