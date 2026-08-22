"""Attempt + suite result upload / list / share / delete."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from services.registry.access import AccessPolicy
from services.registry.blob_io import read_blob, sha256_file
from services.registry.dataset import (
    BOUND_DRAFT,
    BOUND_RELEASE,
    BOUND_UNKNOWN,
    is_draft_version,
    suite_is_complete,
    task_ids_from_file_paths,
    task_set_digest,
)
from services.registry.errors import RegistryAppError
from services.registry.official import official_dataset_ids
from services.registry.runtime_service import attach_agent_refs
from services.registry.store import (
    AttemptResultRow,
    SuiteResultRow,
    TokenInfo,
    _normalize_user_id,
    _run_ids_from_tasks_json,
    attempt_to_dict,
    now,
    share_to_dict,
    suite_to_dict,
)

_SECRET_PATTERNS = (
    re.compile(rb"(?i)-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(rb"(?i)AGEVAL_REGISTRY_TOKEN\s*="),
    re.compile(rb"(?i)github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"(?i)ghp_[A-Za-z0-9]{20,}"),
)


def _previous_run_ids(ref: dict[str, Any]) -> set[str]:
    raw = ref.get("previous")
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        rid = item.get("run_id")
        if rid is None:
            continue
        text = str(rid).strip()
        if text:
            out.add(text)
    return out


def _current_run_ids(ref: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    rid = ref.get("run_id")
    if rid is not None and str(rid).strip():
        out.add(str(rid).strip())
    extra = ref.get("attempt_run_ids")
    if isinstance(extra, list):
        for item in extra:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.add(text)
    return out


def _archive_looks_like_secret_leak(archive: Path) -> bool:
    with archive.open("rb") as fh:
        sample = fh.read(4_000_000)
    return any(p.search(sample) for p in _SECRET_PATTERNS)


class ResultService:
    def __init__(
        self,
        meta: Any,
        blobs: Any,
        access: AccessPolicy,
        *,
        max_upload: int,
    ) -> None:
        self.meta = meta
        self.blobs = blobs
        self.access = access
        self.max_upload = max_upload

    def get_attempt(self, run_id: str) -> Any:
        return self.meta.get_attempt(run_id)

    def get_suite(self, suite_run_id: str) -> Any:
        return self.meta.get_suite(suite_run_id)

    def can_manage(self, result_kind: str, result_id: str, auth: TokenInfo) -> bool:
        return self.access.can_manage_result(result_kind, result_id, auth, for_read=False)

    def upload_attempt(
        self, *, meta: dict[str, Any], archive: Path, auth: TokenInfo
    ) -> dict[str, Any]:
        size_on_disk = archive.stat().st_size
        if size_on_disk > self.max_upload:
            raise RegistryAppError(
                "payload_too_large",
                f"max {self.max_upload} bytes",
                http_status=413,
            )
        run_id = str(meta.get("run_id") or "")
        dataset_id = str(meta.get("dataset_id") or "")
        task_id = str(meta.get("task_id") or "")
        lock_digest = str(meta.get("lock_digest") or "")
        status = str(meta.get("status") or "")
        visibility = str(meta.get("visibility") or "private")
        blob_digest = str(meta.get("blob_digest") or "")
        size = int(meta.get("size") or size_on_disk)
        suite_run_id = str(meta.get("suite_run_id") or "").strip()
        environment = str(meta.get("environment") or "").strip()
        agent_label = str(meta.get("agent_label") or "").strip()
        model_label = str(meta.get("model_label") or "").strip()
        score: float | None = None
        raw_score = meta.get("score")
        if isinstance(raw_score, bool):
            raw_score = None
        if isinstance(raw_score, int | float):
            score = float(raw_score)
        if not run_id or not dataset_id:
            raise RegistryAppError(
                "invalid_request",
                "run_id and dataset_id required",
                http_status=400,
            )
        if visibility not in {"private", "public"}:
            raise RegistryAppError("invalid_request", "bad visibility", http_status=400)
        actual_blob = sha256_file(archive)
        if actual_blob != blob_digest or size != size_on_disk:
            raise RegistryAppError(
                "digest_mismatch",
                "blob digest or size mismatch",
                http_status=400,
            )
        if _archive_looks_like_secret_leak(archive):
            raise RegistryAppError(
                "secret_scan_failed",
                "archive rejected: possible credential material",
                http_status=400,
            )
        replace = bool(meta.get("replace")) or str(meta.get("replace") or "").lower() in {
            "1",
            "true",
            "yes",
        }
        existing = self.meta.get_attempt(run_id)
        if existing is not None:
            if not replace:
                raise RegistryAppError(
                    "conflict",
                    "attempt result already exists",
                    http_status=409,
                )
            if not (
                AccessPolicy.is_admin(auth.scopes)
                or (auth.user_id and existing.uploaded_by == auth.user_id)
            ):
                raise RegistryAppError("not_found", "attempt not found", http_status=404)
            self.meta.delete_attempt(run_id)
            self._gc_attempt_blob(existing.blob_digest)
        row = AttemptResultRow(
            run_id=run_id,
            dataset_id=dataset_id,
            task_id=task_id,
            lock_digest=lock_digest,
            status=status,
            visibility=visibility,
            blob_digest=blob_digest,
            size=size,
            created_at=now(),
            uploaded_by=auth.user_id or "",
            suite_run_id=suite_run_id,
            environment=environment,
            agent_label=agent_label,
            model_label=model_label,
            score=score,
        )
        try:
            self.blobs.put_if_absent(blob_digest, archive, prefix="results")
            self.meta.insert_attempt(row)
        except ValueError as exc:
            raise RegistryAppError(
                "conflict",
                "attempt result already exists",
                http_status=409,
            ) from exc
        payload = attempt_to_dict(row)
        if existing is not None and replace:
            payload["replaced"] = True
        return payload

    def list_attempts(
        self,
        *,
        auth: TokenInfo,
        dataset_id: str | None,
        task_id: str | None = None,
        standalone: bool = False,
    ) -> dict[str, Any]:
        rows = self.meta.list_attempts(
            dataset_id=dataset_id or None,
            task_id=task_id or None,
            standalone=standalone,
            include_private=True,
        )
        items = [attempt_to_dict(r) for r in rows if self._visible_attempt(r, auth)]
        return {"items": items}

    def serve_attempt_meta(self, *, run_id: str, auth: TokenInfo) -> dict[str, Any]:
        return attempt_to_dict(self._require_visible_attempt(run_id, auth))

    def serve_attempt_content(
        self, *, run_id: str, auth: TokenInfo
    ) -> tuple[Any, int, AttemptResultRow]:
        row = self._require_visible_attempt(run_id, auth)
        size = self.blobs.size(row.blob_digest, prefix="results")
        fh = self.blobs.open(row.blob_digest, prefix="results")
        if fh is None or size is None:
            raise RegistryAppError("not_found", "blob missing", http_status=404)
        return fh, int(size), row

    def list_attempt_files(self, *, run_id: str, auth: TokenInfo) -> dict[str, Any]:
        from services.registry.package_files import get_or_build_index

        row = self._require_visible_attempt(run_id, auth)
        archive = read_blob(self.blobs, row.blob_digest, prefix="results")
        if archive is None:
            raise RegistryAppError("not_found", "blob missing", http_status=404)
        try:
            index = get_or_build_index(archive, package_digest=row.blob_digest)
        except Exception as exc:  # noqa: BLE001
            raise RegistryAppError(
                "archive_error",
                f"cannot index attempt: {exc}",
                http_status=500,
            ) from exc
        return {
            "run_id": row.run_id,
            "dataset_id": row.dataset_id,
            "task_id": row.task_id,
            "digest": row.blob_digest,
            "items": index.list_items(),
        }

    def read_attempt_file(self, *, run_id: str, file_path: str, auth: TokenInfo) -> dict[str, Any]:
        from services.registry.package_files import (
            MAX_FILE_BYTES,
            PackageFileNotFound,
            PackageFileTooLarge,
            PackagePathError,
            file_payload,
            normalize_package_path,
            read_member,
        )

        row = self._require_visible_attempt(run_id, auth)
        try:
            safe_path = normalize_package_path(file_path)
        except PackagePathError as exc:
            raise RegistryAppError("invalid_path", str(exc), http_status=400) from exc
        archive = read_blob(self.blobs, row.blob_digest, prefix="results")
        if archive is None:
            raise RegistryAppError("not_found", "blob missing", http_status=404)
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
                extra={"max_bytes": MAX_FILE_BYTES, "path": exc.path, "size": exc.size},
            ) from exc
        return file_payload(safe_path, data, size=size, truncated=truncated)

    def upload_suite(
        self, *, meta: dict[str, Any], archive: Path, auth: TokenInfo
    ) -> dict[str, Any]:
        size_on_disk = archive.stat().st_size
        if size_on_disk > self.max_upload:
            raise RegistryAppError(
                "payload_too_large",
                f"max {self.max_upload} bytes",
                http_status=413,
            )
        suite_run_id = str(meta.get("suite_run_id") or "")
        dataset_id = str(meta.get("dataset_id") or "")
        dataset_version = str(meta.get("dataset_version") or "")
        visibility = str(meta.get("visibility") or "private")
        blob_digest = str(meta.get("blob_digest") or "")
        size = int(meta.get("size") or size_on_disk)
        if not suite_run_id or not dataset_id:
            raise RegistryAppError(
                "invalid_request",
                "suite_run_id and dataset_id required",
                http_status=400,
            )
        if visibility not in {"private", "public"}:
            raise RegistryAppError("invalid_request", "bad visibility", http_status=400)
        if "pass" in meta or "verdict" in meta or meta.get("suite_pass") is not None:
            raise RegistryAppError(
                "invalid_request",
                "suite-level PASS/verdict fields are not accepted",
                http_status=400,
            )
        actual_blob = sha256_file(archive)
        if actual_blob != blob_digest or size != size_on_disk:
            raise RegistryAppError(
                "digest_mismatch",
                "blob digest or size mismatch",
                http_status=400,
            )
        if _archive_looks_like_secret_leak(archive):
            raise RegistryAppError(
                "secret_scan_failed",
                "archive rejected: possible credential material",
                http_status=400,
            )
        metrics: dict[str, Any] = meta["metrics"] if isinstance(meta.get("metrics"), dict) else {}
        task_refs: list[Any] = (
            list(meta["task_refs"]) if isinstance(meta.get("task_refs"), list) else []
        )
        try:
            pass_rate = float(meta.get("pass_rate", metrics.get("pass_rate", 0.0)))
            mean_score = float(meta.get("mean_score", metrics.get("mean_score", 0.0)))
        except (TypeError, ValueError) as exc:
            raise RegistryAppError(
                "invalid_request",
                "pass_rate/mean_score must be numeric",
                http_status=400,
            ) from exc
        try:
            exit_code = int(meta.get("exit_code", 0))
        except (TypeError, ValueError):
            exit_code = 0
        config_payload: dict[str, Any] = {}
        if meta.get("config_fingerprint"):
            config_payload["config_fingerprint"] = str(meta["config_fingerprint"])
        if "config_homogeneous" in meta:
            config_payload["config_homogeneous"] = bool(meta.get("config_homogeneous"))
        actors_raw = meta.get("actors_summary")
        if isinstance(actors_raw, list):
            config_payload["actors_summary"] = [a for a in actors_raw if isinstance(a, dict)]
        overlay_raw = meta.get("job_overlay")
        if isinstance(overlay_raw, dict) and overlay_raw:
            config_payload["job_overlay"] = overlay_raw
        plugins_raw = meta.get("plugins")
        if isinstance(plugins_raw, list):
            plugins: list[dict[str, str]] = []
            seen: set[str] = set()
            for item in plugins_raw:
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("plugin_id") or "").strip()
                key = pid.casefold()
                if not pid or key in seen or key in {"default", "acp", "openai-http"}:
                    continue
                seen.add(key)
                row = {"plugin_id": pid}
                ver = str(item.get("version") or "").strip()
                if ver:
                    row["version"] = ver
                plugins.append(row)
            if plugins:
                config_payload["plugins"] = plugins
        replace = bool(meta.get("replace")) or str(meta.get("replace") or "").lower() in {
            "1",
            "true",
            "yes",
        }
        existing = self.meta.get_suite(suite_run_id)
        if existing is not None:
            if not replace:
                raise RegistryAppError(
                    "conflict",
                    "suite result already exists",
                    http_status=409,
                )
            if not (
                AccessPolicy.is_admin(auth.scopes)
                or (auth.user_id and existing.uploaded_by == auth.user_id)
            ):
                raise RegistryAppError("not_found", "suite not found", http_status=404)
            self.meta.delete_suite(suite_run_id)
            self._gc_suite_blob(existing.blob_digest)
        bound_kind, bound_ids = self._bound_task_ids(dataset_id, dataset_version, auth=auth)
        digest = task_set_digest(bound_ids) if bound_ids else ""
        complete = suite_is_complete(bound_task_ids=bound_ids, task_refs=task_refs)
        row = SuiteResultRow(
            suite_run_id=suite_run_id,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            visibility=visibility,
            pass_rate=pass_rate,
            mean_score=mean_score,
            metrics_json=json.dumps(metrics, sort_keys=True),
            tasks_json=json.dumps(task_refs, sort_keys=True),
            agent_label=str(meta.get("agent_label") or ""),
            model_label=str(meta.get("model_label") or ""),
            blob_digest=blob_digest,
            size=size,
            exit_code=exit_code,
            created_at=now(),
            config_json=json.dumps(config_payload, sort_keys=True),
            uploaded_by=auth.user_id or "",
            complete=complete,
            bound_kind=bound_kind,
            task_set_digest=digest,
        )
        try:
            self.blobs.put_if_absent(blob_digest, archive, prefix="suite-results")
            self.meta.insert_suite(row)
        except ValueError as exc:
            raise RegistryAppError(
                "conflict",
                "suite result already exists",
                http_status=409,
            ) from exc
        payload = suite_to_dict(row)
        if existing is not None and replace:
            payload["replaced"] = True
        return payload

    def append_suite_slot(
        self, *, suite_run_id: str, body: dict[str, Any], auth: TokenInfo
    ) -> dict[str, Any]:
        """Point one scoring slot at a new uploaded Attempt; keep previous[] + old blobs."""
        if body.get("replace") is not None:
            raise RegistryAppError(
                "invalid_request",
                "slot append must not use replace",
                http_status=400,
            )
        existing = self.meta.get_suite(suite_run_id)
        if existing is None:
            raise RegistryAppError("not_found", "suite not found", http_status=404)
        if not (
            AccessPolicy.is_admin(auth.scopes)
            or (auth.user_id and existing.uploaded_by == auth.user_id)
        ):
            raise RegistryAppError("not_found", "suite not found", http_status=404)
        if "pass" in body or "verdict" in body or body.get("suite_pass") is not None:
            raise RegistryAppError(
                "invalid_request",
                "suite-level PASS/verdict fields are not accepted",
                http_status=400,
            )
        task_id = str(body.get("task_id") or "").strip()
        new_run_id = str(body.get("run_id") or "").strip()
        if not task_id or not new_run_id:
            raise RegistryAppError(
                "invalid_request",
                "task_id and run_id required",
                http_status=400,
            )
        try:
            attempt_index = int(body.get("attempt_index") or 0)
        except (TypeError, ValueError) as exc:
            raise RegistryAppError(
                "invalid_request",
                "attempt_index must be an integer ≥ 0",
                http_status=400,
            ) from exc
        if attempt_index < 0:
            raise RegistryAppError(
                "invalid_request",
                "attempt_index must be an integer ≥ 0",
                http_status=400,
            )
        attempt = self.meta.get_attempt(new_run_id)
        if attempt is None:
            raise RegistryAppError(
                "invalid_request",
                "run_id is missing",
                http_status=400,
            )
        if attempt.suite_run_id and attempt.suite_run_id != suite_run_id:
            raise RegistryAppError(
                "invalid_request",
                "run_id belongs to another suite",
                http_status=400,
            )
        if attempt.dataset_id and attempt.dataset_id != existing.dataset_id:
            raise RegistryAppError(
                "invalid_request",
                "run_id dataset_id does not match the suite",
                http_status=400,
            )
        incoming_fp = str(body.get("config_fingerprint") or "").strip()
        try:
            stored_cfg = json.loads(existing.config_json or "{}")
        except (json.JSONDecodeError, TypeError):
            stored_cfg = {}
        stored_fp = ""
        if isinstance(stored_cfg, dict):
            stored_fp = str(stored_cfg.get("config_fingerprint") or "").strip()
        if incoming_fp and stored_fp and incoming_fp != stored_fp:
            raise RegistryAppError(
                "invalid_request",
                "replace-slot requires the same config_fingerprint / job overlay",
                http_status=400,
            )
        task_refs = body.get("task_refs")
        if not isinstance(task_refs, list) or not task_refs:
            raise RegistryAppError(
                "invalid_request",
                "task_refs required",
                http_status=400,
            )
        hit: dict[str, Any] | None = None
        for raw in task_refs:
            if isinstance(raw, dict) and str(raw.get("task_id") or "") == task_id:
                hit = raw
                break
        if hit is None:
            raise RegistryAppError(
                "invalid_request",
                f"task_refs missing task {task_id}",
                http_status=400,
            )
        current_ids = {str(hit.get("run_id") or "").strip()}
        extra_ids = hit.get("attempt_run_ids")
        if isinstance(extra_ids, list):
            current_ids.update(str(x).strip() for x in extra_ids if x is not None)
        if new_run_id not in current_ids:
            raise RegistryAppError(
                "invalid_request",
                "task_refs current pointer must be the new run_id",
                http_status=400,
            )
        try:
            old_refs = json.loads(existing.tasks_json)
        except (json.JSONDecodeError, TypeError):
            old_refs = []
        old_hit = None
        if isinstance(old_refs, list):
            for raw in old_refs:
                if isinstance(raw, dict) and str(raw.get("task_id") or "") == task_id:
                    old_hit = raw
                    break
        if isinstance(old_hit, dict):
            dropped = _current_run_ids(old_hit) - _current_run_ids(hit)
            prev_ids = _previous_run_ids(hit)
            if dropped and not dropped <= prev_ids:
                raise RegistryAppError(
                    "invalid_request",
                    "previous[] must keep the outgoing current",
                    http_status=400,
                )
        metrics: dict[str, Any] = body["metrics"] if isinstance(body.get("metrics"), dict) else {}
        try:
            pass_rate = float(body.get("pass_rate", metrics.get("pass_rate", 0.0)))
            mean_score = float(body.get("mean_score", metrics.get("mean_score", 0.0)))
        except (TypeError, ValueError) as exc:
            raise RegistryAppError(
                "invalid_request",
                "pass_rate/mean_score must be numeric",
                http_status=400,
            ) from exc
        try:
            exit_code = int(body.get("exit_code", existing.exit_code))
        except (TypeError, ValueError):
            exit_code = existing.exit_code
        _bound_kind, bound_ids = self._bound_task_ids(
            existing.dataset_id, existing.dataset_version, auth=auth
        )
        complete = suite_is_complete(bound_task_ids=bound_ids, task_refs=task_refs)
        row = self.meta.update_suite_slot(
            suite_run_id,
            pass_rate=pass_rate,
            mean_score=mean_score,
            metrics_json=json.dumps(metrics, sort_keys=True),
            tasks_json=json.dumps(task_refs, sort_keys=True),
            exit_code=exit_code,
            complete=complete,
        )
        payload = suite_to_dict(row)
        payload["amended"] = True
        return payload

    def list_suites(
        self,
        *,
        auth: TokenInfo,
        dataset_id: str | None,
        board: bool = False,
        uploaded_by: str | None = None,
    ) -> dict[str, Any]:
        rows = self.meta.list_suites(dataset_id=dataset_id or None, include_private=True)
        visible = [r for r in rows if self._visible_suite(r, auth)]
        if uploaded_by:
            want = (
                (auth.user_id or "")
                if uploaded_by.strip().casefold() == "me"
                else uploaded_by.strip()
            )
            visible = [] if not want else [r for r in visible if r.uploaded_by == want]
        if board:
            visible = [
                r
                for r in visible
                if r.complete and r.bound_kind == BOUND_RELEASE and r.board_listed
            ]
        attempt_ids = self._suite_visible_attempt_ids(visible, auth=auth)
        official = official_dataset_ids(self.meta.list_releases(include_private=True))
        consents = self.meta.list_agent_consents_for_suites([r.suite_run_id for r in visible])
        return {
            "items": [
                attach_agent_refs(
                    suite_to_dict(r, attempt_content_ids=attempt_ids),
                    official,
                    consented=consents.get(r.suite_run_id) or set(),
                )
                for r in visible
            ]
        }

    def serve_suite_meta(self, *, suite_run_id: str, auth: TokenInfo) -> dict[str, Any]:
        row = self._require_visible_suite(suite_run_id, auth)
        attempt_ids = self._suite_visible_attempt_ids([row], auth=auth)
        official = official_dataset_ids(self.meta.list_releases(include_private=True))
        consented = set(self.meta.list_agent_consents(suite_run_id))
        return attach_agent_refs(
            suite_to_dict(row, attempt_content_ids=attempt_ids),
            official,
            consented=consented,
        )

    def attach_agent(
        self,
        *,
        suite_run_id: str,
        agent: str,
        auth: TokenInfo,
        role: str | None = None,
        grant_consent: bool | None = None,
        skip_owner_check: bool = False,
    ) -> dict[str, Any]:
        """Write published ``agent_ref`` onto the stored suite overlay.

        Compare/write is this method only. Callers (CLI, Hub, appearance
        approve) must not reimplement ``_binding_role_key``. Lock bytes and
        ``config_fingerprint`` stay as uploaded. Agent-org owners also grant
        appearance consent; other uploaders only stamp provenance.
        """
        from services.registry.package_service import _agent_preview_from_archive
        from services.registry.store import package_kind_for_media_type

        from ageval.application.suite.attach_agent_ref import (
            AttachAgentRefError,
            format_published_agent_ref,
            inject_published_agent_ref,
            parse_published_agent_spec,
        )

        row = self.meta.get_suite(suite_run_id)
        if row is None or (
            not skip_owner_check
            and not self.access.can_manage_result("suite", suite_run_id, auth, for_read=False)
        ):
            raise RegistryAppError("not_found", "suite not found", http_status=404)
        try:
            spec_role, package_id, version = parse_published_agent_spec(agent)
        except AttachAgentRefError as exc:
            raise RegistryAppError(exc.error_code, exc.message, http_status=400) from exc
        want_role = (role or "").strip() or spec_role
        if role and spec_role and role.strip() != spec_role:
            raise RegistryAppError(
                "invalid_request",
                "conflicting role in --agent and --role",
                http_status=400,
            )
        release = self.meta.get_by_version(package_id, version)
        if release is None or not self.access.visible_package(release, auth):
            raise RegistryAppError("not_found", "agent package not found", http_status=404)
        try:
            kind = package_kind_for_media_type(release.media_type)
        except ValueError as exc:
            raise RegistryAppError("invalid_request", str(exc), http_status=400) from exc
        if kind != "agent":
            raise RegistryAppError(
                "invalid_request",
                "agent ref must name an agent package",
                http_status=400,
            )
        data = read_blob(self.blobs, release.blob_digest, prefix="packages")
        if data is None:
            raise RegistryAppError("not_found", "agent package blob missing", http_status=404)
        preview = _agent_preview_from_archive(data)
        binding = preview.get("binding")
        if not isinstance(binding, Mapping):
            raise RegistryAppError(
                "invalid_request",
                "published agent binding is missing",
                http_status=400,
            )
        agent_ref = format_published_agent_ref(package_id, version, release.package_digest)
        try:
            cfg = json.loads(row.config_json or "{}")
        except (json.JSONDecodeError, TypeError):
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        overlay = cfg.get("job_overlay")
        fingerprint_before = cfg.get("config_fingerprint")
        try:
            result = inject_published_agent_ref(
                overlay if isinstance(overlay, Mapping) else None,
                published_binding=binding,
                agent_ref=agent_ref,
                role=want_role,
            )
        except AttachAgentRefError as exc:
            raise RegistryAppError(exc.error_code, exc.message, http_status=400) from exc
        if result.changed:
            cfg["job_overlay"] = result.overlay
            if fingerprint_before is not None:
                cfg["config_fingerprint"] = fingerprint_before
            self.meta.update_suite_config_json(suite_run_id, json.dumps(cfg, sort_keys=True))
        agent_org_owner = bool(
            release.org_id
            and self.access.org_owner_status(org_id=release.org_id, auth=auth) == "ok"
        )
        if grant_consent is True or (grant_consent is None and agent_org_owner):
            self.meta.grant_agent_consent(
                suite_run_id=suite_run_id,
                package_id=package_id,
                granted_by=auth.user_id or "",
                source="attach",
            )
        if skip_owner_check:
            stored = self.meta.get_suite(suite_run_id)
            if stored is None:
                raise RegistryAppError("not_found", "suite not found", http_status=404)
            official = official_dataset_ids(self.meta.list_releases(include_private=True))
            consented = set(self.meta.list_agent_consents(suite_run_id))
            payload = attach_agent_refs(suite_to_dict(stored), official, consented=consented)
        else:
            payload = self.serve_suite_meta(suite_run_id=suite_run_id, auth=auth)
        payload["attached"] = True
        payload["idempotent"] = not result.changed
        payload["attached_roles"] = list(result.roles)
        payload["agent_ref"] = result.agent_ref
        return payload

    def serve_suite_content(
        self, *, suite_run_id: str, auth: TokenInfo
    ) -> tuple[Any, int, SuiteResultRow]:
        row = self._require_visible_suite(suite_run_id, auth)
        size = self.blobs.size(row.blob_digest, prefix="suite-results")
        fh = self.blobs.open(row.blob_digest, prefix="suite-results")
        if fh is None or size is None:
            raise RegistryAppError("not_found", "blob missing", http_status=404)
        return fh, int(size), row

    def list_shares(self, *, result_kind: str, result_id: str, auth: TokenInfo) -> dict[str, Any]:
        if not self.access.can_manage_result(result_kind, result_id, auth, for_read=True):
            raise RegistryAppError("not_found", "result not found", http_status=404)
        shares = self.meta.list_result_shares(result_kind=result_kind, result_id=result_id)
        return {
            "result_kind": result_kind,
            "result_id": result_id,
            "items": [share_to_dict(s) for s in shares],
        }

    def add_share(
        self,
        *,
        result_kind: str,
        result_id: str,
        target_type: str,
        target_id: str,
        auth: TokenInfo,
    ) -> dict[str, Any]:
        if not self.can_manage(result_kind, result_id, auth):
            raise RegistryAppError("not_found", "result not found", http_status=404)
        target_type = target_type.strip()
        target_id = target_id.strip()
        if target_type not in {"org", "user"} or not target_id:
            raise RegistryAppError(
                "invalid_request",
                "target_type (org|user) and target_id required",
                http_status=400,
            )
        if target_type == "user":
            target_id = _normalize_user_id(target_id) or target_id.casefold()
        else:
            target_id = target_id.casefold()
            if self.meta.get_org(target_id) is None:
                raise RegistryAppError(
                    "org_not_found",
                    f"org {target_id!r} not found",
                    http_status=400,
                )
        try:
            share = self.meta.add_result_share(
                result_kind=result_kind,
                result_id=result_id,
                target_type=target_type,
                target_id=target_id,
            )
        except ValueError as exc:
            raise RegistryAppError("conflict", "share already exists", http_status=409) from exc
        return share_to_dict(share)

    def remove_share(
        self,
        *,
        result_kind: str,
        result_id: str,
        target_type: str,
        target_id: str,
        auth: TokenInfo,
    ) -> dict[str, Any]:
        if not self.can_manage(result_kind, result_id, auth):
            raise RegistryAppError("not_found", "result not found", http_status=404)
        target_type = target_type.strip()
        target_id = target_id.strip()
        if target_type == "user":
            target_id = _normalize_user_id(target_id) or target_id.casefold()
        else:
            target_id = target_id.casefold()
        try:
            self.meta.remove_result_share(
                result_kind=result_kind,
                result_id=result_id,
                target_type=target_type,
                target_id=target_id,
            )
        except LookupError as exc:
            raise RegistryAppError("not_found", "share not found", http_status=404) from exc
        return {"ok": True}

    def delete_attempt(self, *, run_id: str, auth: TokenInfo) -> dict[str, Any]:
        if not self.can_manage("attempt", run_id, auth):
            raise RegistryAppError("not_found", "attempt not found", http_status=404)
        row = self.meta.get_attempt(run_id)
        if row is None:
            raise RegistryAppError("not_found", "attempt not found", http_status=404)
        blob_deleted = self._delete_attempt_row(row)
        return {
            "ok": True,
            "result_kind": "attempt",
            "result_id": run_id,
            "blob_deleted": blob_deleted,
        }

    def delete_suite(
        self, *, suite_run_id: str, with_attempts: bool, auth: TokenInfo
    ) -> dict[str, Any]:
        if not self.can_manage("suite", suite_run_id, auth):
            raise RegistryAppError("not_found", "suite not found", http_status=404)
        row = self.meta.get_suite(suite_run_id)
        if row is None:
            raise RegistryAppError("not_found", "suite not found", http_status=404)
        deleted_attempts: list[str] = []
        skipped_attempts: list[str] = []
        if with_attempts:
            for att in self._collect_suite_linked_attempts(row):
                if not (
                    AccessPolicy.is_admin(auth.scopes)
                    or (auth.user_id and att.uploaded_by == auth.user_id)
                ):
                    skipped_attempts.append(att.run_id)
                    continue
                self._delete_attempt_row(att)
                deleted_attempts.append(att.run_id)
        self.meta.delete_suite(suite_run_id)
        blob_deleted = self._gc_suite_blob(row.blob_digest)
        payload: dict[str, Any] = {
            "ok": True,
            "result_kind": "suite",
            "result_id": suite_run_id,
            "blob_deleted": blob_deleted,
            "with_attempts": with_attempts,
            "deleted_attempts": deleted_attempts,
        }
        if skipped_attempts:
            payload["skipped_attempts"] = skipped_attempts
        return payload

    def patch_attempt(self, *, run_id: str, visibility: str, auth: TokenInfo) -> dict[str, Any]:
        if not self.can_manage("attempt", run_id, auth):
            raise RegistryAppError("not_found", "attempt not found", http_status=404)
        if visibility not in {"public", "private"}:
            raise RegistryAppError(
                "invalid_request",
                "visibility must be public or private",
                http_status=400,
            )
        try:
            row = self.meta.set_attempt_visibility(run_id, visibility)
        except LookupError as exc:
            raise RegistryAppError("not_found", "attempt not found", http_status=404) from exc
        return attempt_to_dict(row)

    def patch_suite(self, *, suite_run_id: str, visibility: str, auth: TokenInfo) -> dict[str, Any]:
        if not self.can_manage("suite", suite_run_id, auth):
            raise RegistryAppError("not_found", "suite not found", http_status=404)
        if visibility not in {"public", "private"}:
            raise RegistryAppError(
                "invalid_request",
                "visibility must be public or private",
                http_status=400,
            )
        try:
            row = self.meta.set_suite_visibility(suite_run_id, visibility)
        except LookupError as exc:
            raise RegistryAppError("not_found", "suite not found", http_status=404) from exc
        return suite_to_dict(row)

    def _visible_attempt(self, row: AttemptResultRow, auth: TokenInfo) -> bool:
        return self.access.visible_result(
            result_kind="attempt",
            result_id=row.run_id,
            visibility=row.visibility,
            uploaded_by=row.uploaded_by,
            auth=auth,
        )

    def _bound_task_ids(
        self, dataset_id: str, dataset_version: str, *, auth: TokenInfo
    ) -> tuple[str, frozenset[str]]:
        """Resolve bound package + task set at upload time.

        Release match wins. Otherwise a live draft the caller may see is
        draft-bound. Unauthorized draft reads and missing packages → unknown
        / empty set (incomplete, not on the public board; no existence leak).
        """
        release = None
        draft = None
        if is_draft_version(dataset_version):
            draft = self.meta.get_draft(dataset_id)
            if draft is not None and not self.access.entitled_to_draft(draft, auth):
                return BOUND_UNKNOWN, frozenset()
            kind = BOUND_DRAFT if draft is not None else BOUND_UNKNOWN
        else:
            release = self.meta.get_by_version(dataset_id, dataset_version)
            if release is not None:
                kind = BOUND_RELEASE
            else:
                draft = self.meta.get_draft(dataset_id)
                if draft is not None and not self.access.entitled_to_draft(draft, auth):
                    return BOUND_UNKNOWN, frozenset()
                kind = BOUND_DRAFT if draft is not None else BOUND_UNKNOWN
        blob = None
        digest = ""
        if release is not None:
            blob = read_blob(self.blobs, release.blob_digest, prefix="packages")
            digest = release.package_digest
        elif draft is not None:
            blob = read_blob(self.blobs, draft.blob_digest, prefix="packages")
            digest = draft.package_digest
        if blob is None:
            return kind, frozenset()
        try:
            from services.registry.package_files import get_or_build_index

            index = get_or_build_index(blob, package_digest=digest or "bound")
            paths = [item.get("path") or "" for item in index.list_items()]
        except Exception:  # noqa: BLE001 — fail closed to incomplete
            return kind, frozenset()
        return kind, task_ids_from_file_paths(paths)

    def _visible_suite(self, row: SuiteResultRow, auth: TokenInfo) -> bool:
        return self.access.visible_result(
            result_kind="suite",
            result_id=row.suite_run_id,
            visibility=row.visibility,
            uploaded_by=row.uploaded_by,
            auth=auth,
        )

    def _require_visible_attempt(self, run_id: str, auth: TokenInfo) -> AttemptResultRow:
        row = self.meta.get_attempt(run_id)
        if row is None or not self._visible_attempt(row, auth):
            raise RegistryAppError("not_found", "attempt not found", http_status=404)
        return row

    def _require_visible_suite(self, suite_run_id: str, auth: TokenInfo) -> SuiteResultRow:
        row = self.meta.get_suite(suite_run_id)
        if row is None or not self._visible_suite(row, auth):
            raise RegistryAppError("not_found", "suite not found", http_status=404)
        return row

    def _suite_visible_attempt_ids(
        self, rows: list[SuiteResultRow], *, auth: TokenInfo
    ) -> set[str]:
        run_ids: list[str] = []
        for r in rows:
            run_ids.extend(_run_ids_from_tasks_json(r.tasks_json))
        try:
            attempts = self.meta.attempts_for_ids(run_ids)
        except Exception:  # noqa: BLE001
            return set()
        return {a.run_id for a in attempts if self._visible_attempt(a, auth)}

    def _gc_attempt_blob(self, blob_digest: str) -> bool:
        if not blob_digest:
            return False
        if self.meta.count_attempt_blob_refs(blob_digest) > 0:
            return False
        return bool(self.blobs.delete(blob_digest, prefix="results"))

    def _gc_suite_blob(self, blob_digest: str) -> bool:
        if not blob_digest:
            return False
        if self.meta.count_suite_blob_refs(blob_digest) > 0:
            return False
        return bool(self.blobs.delete(blob_digest, prefix="suite-results"))

    def _delete_attempt_row(self, row: AttemptResultRow) -> bool:
        self.meta.delete_attempt(row.run_id)
        return self._gc_attempt_blob(row.blob_digest)

    def _collect_suite_linked_attempts(self, suite_row: SuiteResultRow) -> list[AttemptResultRow]:
        by_id: dict[str, AttemptResultRow] = {}
        for att in self.meta.list_attempts_for_suite(suite_row.suite_run_id):
            by_id[att.run_id] = att
        run_ids = list(_run_ids_from_tasks_json(suite_row.tasks_json))
        try:
            refs = json.loads(suite_row.tasks_json)
        except (json.JSONDecodeError, TypeError):
            refs = []
        if isinstance(refs, list):
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                extra = ref.get("attempt_run_ids")
                if isinstance(extra, list):
                    for rid in extra:
                        text = str(rid or "").strip()
                        if text:
                            run_ids.append(text)
        for att in self.meta.attempts_for_ids(run_ids):
            by_id[att.run_id] = att
        return list(by_id.values())
