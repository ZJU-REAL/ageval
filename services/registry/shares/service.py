"""Suite snapshot shares: a static archive, or a live same-token patch.

Creates a capability URL. Does not write suite visibility, result_shares,
or board_listed. Live mode stores a mutable summary plus per-path objects
under the same ``shares/`` prefix. Static mode keeps one archive blob.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import secrets
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.registry.content.blob_io import read_blob, sha256_file
from services.registry.errors import RegistryAppError
from services.registry.shares.rows import SnapshotShareFileRow, SnapshotShareRow
from services.registry.auth.tokens import TokenInfo
from services.registry.clock import now

from ageval.evidence.locators import run_locator, suite_run_locator
from ageval.registry.media_types import SHARE_SNAPSHOT_MEDIA_TYPE
from ageval.registry.share_snapshot import (
    LIVE_SHARE_SIDECAR,
    SHARE_BLOB_PREFIX,
    SNAPSHOT_SHARE_KIND,
    ShareArchiveTooLarge,
    archive_contains_snapshot_marker,
    archive_member_names,
    iter_archive_files,
    read_archive_member,
    scrub_member_bytes,
    scrub_structure,
    scrub_text,
    snapshot_has_plaintext_secret,
    text_has_plaintext_secret,
)

SHARE_MODE_STATIC = "static"
SHARE_MODE_LIVE = "live"

_META_KEYS = frozenset(
    {
        "suite_run_id",
        "dataset_id",
        "dataset_version",
        "blob_digest",
        "size",
        "kind",
        "run_id",
        "mode",
    }
)
_PATCH_KEYS = frozenset({"summary", "heartbeat"})
_ACL_KEYS = frozenset({"visibility", "result_shares", "board_listed"})
_NOTE = "snapshot share; per-task evaluator verdicts only; no suite-level PASS"


@dataclass
class _LiveMember:
    path: str
    digest: str
    size: int
    spool: Path


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
    def __init__(self, shares: Any, blobs: Any, *, max_upload: int) -> None:
        self.shares = shares
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
        mode = self._share_mode(meta)
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
        created = now()
        members: list[_LiveMember] = []
        try:
            stored_size = size
            stored_digest = blob_digest
            if mode == SHARE_MODE_LIVE:
                members = self._live_members(archive)
                stored_size = sum(item.size for item in members)
                summary = self._summary_from_live_members(
                    summary,
                    members,
                    suite_run_id=suite_run_id,
                    dataset_id=dataset_id,
                    dataset_version=dataset_version,
                )
                _stamp_attempt_content(summary, {item.path for item in members})
                stored_digest = ""
            row = SnapshotShareRow(
                token=token,
                owner_user_id=auth.user_id,
                suite_run_id=suite_run_id,
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                blob_digest=stored_digest,
                size=stored_size,
                summary_json=json.dumps(summary, sort_keys=True),
                created_at=created,
                run_id=str(meta.get("run_id") or "").strip(),
                mode=mode,
                updated_at=created,
            )
            if mode == SHARE_MODE_STATIC:
                self.blobs.put_if_absent(blob_digest, archive, prefix=SHARE_BLOB_PREFIX)
            else:
                self._put_live_members(token, members)
            try:
                self.shares.insert_snapshot_share(row)
            except ValueError as exc:
                if mode == SHARE_MODE_LIVE:
                    self._discard_live_members(token, members)
                raise RegistryAppError(
                    "conflict",
                    "snapshot share token collision",
                    http_status=409,
                ) from exc
        finally:
            self._clear_member_spools(members)
        return self._public(row)

    def patch(
        self,
        token: str,
        *,
        meta: dict[str, Any],
        archive: Path | None,
        auth: TokenInfo,
    ) -> dict[str, Any]:
        """Owner update of a live share. Static shares stay immutable."""
        row = self._require_owner(token, auth)
        if row.mode != SHARE_MODE_LIVE:
            raise RegistryAppError(
                "invalid_request",
                "static snapshot share cannot be patched",
                http_status=400,
            )
        forbidden = _ACL_KEYS & set(meta)
        if forbidden:
            raise RegistryAppError(
                "invalid_request",
                "snapshot share does not accept catalog ACL fields",
                http_status=400,
            )
        unknown = set(meta) - _PATCH_KEYS
        if unknown:
            raise RegistryAppError(
                "invalid_request",
                "unknown keys: " + ", ".join(sorted(unknown)),
                http_status=400,
            )
        incoming = meta.get("summary")
        if not isinstance(incoming, dict):
            raise RegistryAppError(
                "invalid_request",
                "summary is required",
                http_status=400,
            )
        summary = self._merged_summary(row, incoming)
        members: list[_LiveMember] = []
        new_size = row.size
        existing: dict[str, SnapshotShareFileRow] = {}
        if archive is not None:
            archive_size = archive.stat().st_size
            if archive_size > self.max_upload:
                raise RegistryAppError(
                    "payload_too_large",
                    f"max {self.max_upload} bytes",
                    http_status=413,
                )
            members = self._live_members(archive, require_marker=False)
            existing = {item.path: item for item in self.shares.list_snapshot_share_files(token)}
            for member in members:
                old = existing.get(member.path)
                new_size += member.size - (old.size if old is not None else 0)
            if new_size > self.max_upload:
                self._clear_member_spools(members)
                raise RegistryAppError(
                    "payload_too_large",
                    f"max {self.max_upload} bytes",
                    http_status=413,
                )
        try:
            if members:
                self._put_live_members(token, members)
                for member in members:
                    old = existing.get(member.path)
                    if old is not None and old.blob_digest != member.digest:
                        self._gc_share_blob(old.blob_digest)
            names = {item.path for item in self.shares.list_snapshot_share_files(token)}
            _stamp_attempt_content(summary, names)
            self.shares.update_snapshot_share(
                token,
                summary_json=json.dumps(summary, sort_keys=True),
                size=new_size,
                updated_at=now(),
            )
        finally:
            self._clear_member_spools(members)
        return self._public(self._require(token))

    def get(self, token: str) -> dict[str, Any]:
        return self._public(self._require(token))

    def find_owned(self, *, auth: TokenInfo, suite_run_id: str, run_id: str) -> dict[str, Any]:
        if not auth.user_id:
            raise RegistryAppError(
                "unauthorized",
                "authentication required",
                http_status=401,
            )
        row = self.shares.find_snapshot_share(
            owner_user_id=auth.user_id,
            suite_run_id=suite_run_id,
            run_id=run_id,
        )
        if row is None:
            return {"ok": True, "shared": False, "suite_run_id": suite_run_id, "run_id": run_id}
        payload = self._public(row)
        payload["ok"] = True
        payload["shared"] = True
        return payload

    def revoke(self, token: str, *, auth: TokenInfo) -> dict[str, Any]:
        row = self._require_owner(token, auth)
        files = self.shares.list_snapshot_share_files(token)
        digests = [row.blob_digest, *(item.blob_digest for item in files)]
        self.shares.delete_snapshot_share_files(token)
        self.shares.delete_snapshot_share(token)
        for digest in dict.fromkeys(digests):
            self._gc_share_blob(digest)
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
        if row.mode == SHARE_MODE_LIVE:
            return self._list_live_files(row, run_id)
        archive = self._archive_bytes(row)
        from services.registry.content.files import get_or_build_index

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
        from services.registry.content.files import (
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
        if row.mode == SHARE_MODE_LIVE:
            return self._read_live_file(row, safe_path)
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
        row = self.shares.get_snapshot_share(token)
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
        if row.mode == SHARE_MODE_LIVE:
            return any(
                item.path.startswith(prefix)
                for item in self.shares.list_snapshot_share_files(row.token)
            )
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
        _stamp_attempt_content(summary, set(archive_member_names(archive)))
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
            "run_id": row.run_id,
            "mode": row.mode or SHARE_MODE_STATIC,
            "updated_at": row.updated_at or row.created_at,
        }
        for key in (
            "status",
            "counts",
            "progress",
            "job_overlay",
            "actors_summary",
            "plugins",
            "config_fingerprint",
            "config_homogeneous",
        ):
            if key in summary:
                payload[key] = summary[key]
        return payload

    def _share_mode(self, meta: dict[str, Any]) -> str:
        raw = meta.get("mode", SHARE_MODE_STATIC)
        if raw in {None, ""}:
            return SHARE_MODE_STATIC
        if raw not in {SHARE_MODE_STATIC, SHARE_MODE_LIVE}:
            raise RegistryAppError(
                "invalid_request",
                "mode must be static or live",
                http_status=400,
            )
        return str(raw)

    def _require_owner(self, token: str, auth: TokenInfo) -> SnapshotShareRow:
        row = self._require(token)
        if not auth.user_id or auth.user_id != row.owner_user_id:
            raise RegistryAppError(
                "forbidden",
                "snapshot share owner required",
                http_status=403,
            )
        return row

    def _live_members(self, archive: Path, *, require_marker: bool = True) -> list[_LiveMember]:
        if require_marker and not archive_contains_snapshot_marker(archive):
            raise RegistryAppError(
                "invalid_request",
                "snapshot-share.json is required",
                http_status=400,
            )
        work = Path(tempfile.mkdtemp(prefix="ageval-live-"))
        members: list[_LiveMember] = []
        seen: set[str] = set()
        total = 0
        ok = False
        try:
            try:
                for name, raw in iter_archive_files(archive, max_total=self.max_upload):
                    total += self._append_live_member(members, seen, work, name, raw, total=total)
            except ShareArchiveTooLarge as exc:
                raise RegistryAppError(
                    "payload_too_large",
                    f"max {self.max_upload} bytes",
                    http_status=413,
                ) from exc
            except (OSError, tarfile.TarError, gzip.BadGzipFile, EOFError) as exc:
                raise RegistryAppError(
                    "invalid_request",
                    "snapshot archive is unreadable",
                    http_status=400,
                ) from exc
            ok = True
            return members
        finally:
            if not ok:
                shutil.rmtree(work, ignore_errors=True)

    def _append_live_member(
        self,
        members: list[_LiveMember],
        seen: set[str],
        work: Path,
        name: str,
        raw: bytes,
        *,
        total: int,
    ) -> int:
        if not name or Path(name).name == LIVE_SHARE_SIDECAR:
            return 0
        path = _safe_member_path(name)
        if path in seen:
            return 0
        seen.add(path)
        data = scrub_member_bytes(path, raw)
        if text_has_plaintext_secret(data):
            raise RegistryAppError(
                "secret_scan_failed",
                "snapshot contains a plaintext secret",
                http_status=400,
            )
        size = len(data)
        if total + size > self.max_upload:
            raise RegistryAppError(
                "payload_too_large",
                f"max {self.max_upload} bytes",
                http_status=413,
            )
        spool = work / str(len(members))
        spool.write_bytes(data)
        members.append(
            _LiveMember(
                path=path,
                digest=_sha256_bytes(data),
                size=size,
                spool=spool,
            )
        )
        return size

    def _summary_from_live_members(
        self,
        summary: dict[str, Any],
        members: list[_LiveMember],
        *,
        suite_run_id: str,
        dataset_id: str,
        dataset_version: str,
    ) -> dict[str, Any]:
        member_name = f"{suite_run_locator(suite_run_id)}/summary.json"
        for item in members:
            if item.path != member_name:
                continue
            parsed = self._summary_object(
                item.spool.read_bytes(),
                suite_run_id=suite_run_id,
                dataset_id=dataset_id,
                dataset_version=dataset_version,
            )
            return parsed
        return summary

    def _summary_object(
        self,
        raw: bytes,
        *,
        suite_run_id: str,
        dataset_id: str,
        dataset_version: str,
    ) -> dict[str, Any]:
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
        self._require_summary_identity(
            summary,
            suite_run_id=suite_run_id,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
        )
        return summary

    def _require_summary_identity(
        self,
        summary: dict[str, Any],
        *,
        suite_run_id: str,
        dataset_id: str,
        dataset_version: str,
    ) -> None:
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

    def _merged_summary(self, row: SnapshotShareRow, incoming: dict[str, Any]) -> dict[str, Any]:
        if _ACL_KEYS & set(incoming):
            raise RegistryAppError(
                "invalid_request",
                "snapshot share does not accept catalog ACL fields",
                http_status=400,
            )
        try:
            current = json.loads(row.summary_json)
        except json.JSONDecodeError:
            current = {}
        if not isinstance(current, dict):
            current = {}
        merged = dict(current)
        merged.update(incoming)
        for field, expected in (
            ("suite_run_id", row.suite_run_id),
            ("dataset_id", row.dataset_id),
            ("dataset_version", row.dataset_version),
        ):
            value = incoming.get(field)
            if value not in {None, ""} and str(value) != expected:
                raise RegistryAppError(
                    "invalid_request",
                    f"{field} does not match the share",
                    http_status=400,
                )
        merged["suite_run_id"] = row.suite_run_id
        merged["dataset_id"] = row.dataset_id
        merged["dataset_version"] = row.dataset_version
        cleaned = scrub_structure(merged)
        encoded = scrub_text(json.dumps(cleaned, sort_keys=True))
        if text_has_plaintext_secret(encoded.encode()):
            raise RegistryAppError(
                "secret_scan_failed",
                "snapshot contains a plaintext secret",
                http_status=400,
            )
        try:
            parsed = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise RegistryAppError(
                "invalid_request",
                "summary is not JSON",
                http_status=400,
            ) from exc
        if not isinstance(parsed, dict):
            raise RegistryAppError(
                "invalid_request",
                "summary must be an object",
                http_status=400,
            )
        return parsed

    def _put_live_members(self, token: str, members: list[_LiveMember]) -> None:
        for item in members:
            self.blobs.put_if_absent(item.digest, item.spool, prefix=SHARE_BLOB_PREFIX)
            self.shares.upsert_snapshot_share_file(
                SnapshotShareFileRow(
                    token=token,
                    path=item.path,
                    blob_digest=item.digest,
                    size=item.size,
                )
            )

    def _discard_live_members(self, token: str, members: list[_LiveMember]) -> None:
        self.shares.delete_snapshot_share_files(token)
        for digest in dict.fromkeys(item.digest for item in members):
            self._gc_share_blob(digest)

    def _clear_member_spools(self, members: list[_LiveMember]) -> None:
        if not members:
            return
        shutil.rmtree(members[0].spool.parent, ignore_errors=True)

    def _gc_share_blob(self, digest: str) -> None:
        if not digest:
            return
        if self.shares.count_snapshot_share_blob_refs(digest):
            return
        if self.shares.count_snapshot_share_file_blob_refs(digest):
            return
        self.blobs.delete(digest, prefix=SHARE_BLOB_PREFIX)

    def _list_live_files(self, row: SnapshotShareRow, run_id: str) -> dict[str, Any]:
        prefix = run_locator(run_id)
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in self.shares.list_snapshot_share_files(row.token):
            path = record.path
            if path != prefix and not path.startswith(prefix + "/"):
                continue
            _add_live_item(items, seen, path, "file", record.size)
            if not path.startswith(prefix + "/"):
                continue
            acc = prefix
            _add_live_item(items, seen, acc, "dir", 0)
            for part in path[len(prefix) + 1 :].split("/")[:-1]:
                acc = f"{acc}/{part}"
                _add_live_item(items, seen, acc, "dir", 0)
        items.sort(key=lambda item: str(item["path"]))
        return {
            "run_id": run_id,
            "dataset_id": row.dataset_id,
            "digest": row.blob_digest,
            "items": items,
        }

    def _read_live_file(self, row: SnapshotShareRow, safe_path: str) -> dict[str, Any]:
        from services.registry.content.files import file_payload

        found = self.shares.get_snapshot_share_file(row.token, safe_path)
        if found is None:
            raise RegistryAppError("not_found", f"file not found: {safe_path}", http_status=404)
        blob = read_blob(self.blobs, found.blob_digest, prefix=SHARE_BLOB_PREFIX)
        if blob is None:
            raise RegistryAppError("not_found", f"file not found: {safe_path}", http_status=404)
        data, size, truncated = _preview_bytes(blob)
        return file_payload(safe_path, data, size=size, truncated=truncated)


def _safe_member_path(name: str) -> str:
    from services.registry.content.files import PackagePathError, normalize_package_path

    try:
        return normalize_package_path(name)
    except PackagePathError as exc:
        raise RegistryAppError("invalid_path", str(exc), http_status=400) from exc


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _stamp_attempt_content(summary: dict[str, Any], names: set[str]) -> None:
    refs = summary.get("task_refs")
    if not isinstance(refs, list):
        return
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


def _add_live_item(
    items: list[dict[str, Any]],
    seen: set[str],
    path: str,
    kind: str,
    size: int,
) -> None:
    if path in seen:
        return
    seen.add(path)
    items.append({"path": path, "type": kind, "size": size})


def _preview_bytes(data: bytes) -> tuple[bytes, int, bool]:
    from services.registry.content.files import MAX_FILE_BYTES

    size = len(data)
    if size <= MAX_FILE_BYTES:
        return data, size, False
    chunk = data[:MAX_FILE_BYTES]
    for drop in range(0, min(4, len(chunk))):
        piece = chunk if drop == 0 else chunk[:-drop]
        try:
            piece.decode("utf-8")
        except UnicodeDecodeError:
            continue
        chunk = piece
        break
    return chunk, size, True


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
