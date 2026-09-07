"""Package publish / list / serve / delete / patch."""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from typing import Any

from services.registry.access import AccessPolicy
from services.registry.blob_io import read_blob, sha256_file
from services.registry.brand_marks import normalize_icon_github, normalize_icon_key
from services.registry.builtin_agents import (
    builtin_agent_item,
    builtin_agent_items,
    is_builtin_agent_id,
    reserved_harness_leaf,
)
from services.registry.builtin_agents import (
    builtin_list_files as builtin_agent_list_files,
)
from services.registry.builtin_agents import (
    builtin_read_file as builtin_agent_read_file,
)
from services.registry.builtin_plugins import (
    builtin_plugin_item,
    builtin_plugin_items,
    is_builtin_plugin_id,
)
from services.registry.dataset import DRAFT_SLOT, is_draft_version
from services.registry.errors import RegistryAppError
from services.registry.paging import page_slice
from services.registry.store import (
    DraftRow,
    ReleaseRow,
    TokenInfo,
    now,
    package_kind_for_media_type,
    release_to_dict,
)


def overlay_kind(dataset_id: str, package_kind: str | None) -> str | None:
    """Which builtin catalog to serve. Omitted kind prefers plugin on collision."""
    want = (package_kind or "").strip().casefold() or None
    if want not in {None, "plugin", "agent"}:
        return None
    plugin = is_builtin_plugin_id(dataset_id)
    agent = is_builtin_agent_id(dataset_id)
    if want == "plugin":
        return "plugin" if plugin else None
    if want == "agent":
        return "agent" if agent else None
    if plugin:
        return "plugin"
    if agent:
        return "agent"
    return None


def _builtin_item(dataset_id: str, kind: str) -> dict[str, Any]:
    item = builtin_plugin_item(dataset_id) if kind == "plugin" else builtin_agent_item(dataset_id)
    if item is None:
        raise RegistryAppError("not_found", f"builtin {kind} not found", http_status=404)
    return item


def _normalize_plugin_name_segment(dataset_id: str, raw: object) -> str:
    """Store only the name leaf. ``org/name`` ids cannot change the org prefix."""
    from services.registry.org_service import _normalize_display_name

    name = _normalize_display_name(raw)
    org, _leaf = (dataset_id.split("/", 1) + [""])[:2] if "/" in dataset_id else ("", dataset_id)
    if "/" in name:
        prefix, rest = name.split("/", 1)
        if org and prefix.casefold() != org.casefold():
            raise RegistryAppError(
                "invalid_request",
                "display_name cannot change the org prefix",
                http_status=400,
            )
        name = _normalize_display_name(rest)
    if not name:
        raise RegistryAppError("invalid_request", "display_name required", http_status=400)
    if "/" in name:
        raise RegistryAppError(
            "invalid_request",
            "display_name is the name after org/, not org/name",
            http_status=400,
        )
    return name


MARKETPLACE_DESCRIPTION_MAX = 500


def _normalize_marketplace_description(raw: object) -> str:
    """Owner-set description override; empty string clears."""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise RegistryAppError("invalid_request", "description must be a string", http_status=400)
    text = raw.strip()
    if len(text) > MARKETPLACE_DESCRIPTION_MAX:
        raise RegistryAppError(
            "invalid_request",
            f"description exceeds {MARKETPLACE_DESCRIPTION_MAX} characters",
            http_status=400,
        )
    return text


class PackageService:
    def __init__(
        self,
        packages: Any,
        orgs: Any,
        blobs: Any,
        access: AccessPolicy,
        *,
        max_upload: int,
    ) -> None:
        self.packages = packages
        self.orgs = orgs
        self.blobs = blobs
        self.access = access
        self.max_upload = max_upload

    def get(self, dataset_id: str, version: str) -> ReleaseRow | None:
        return self.packages.get_by_version(dataset_id, version)

    def can_manage(self, row: ReleaseRow, auth: TokenInfo) -> bool:
        return self.access.can_manage_package(row, auth)

    def _with_download_count(
        self, payload: dict[str, Any], auth: TokenInfo | None = None
    ) -> dict[str, Any]:
        self._with_download_counts([payload], auth=auth)
        return payload

    def _with_download_counts(
        self, items: list[dict[str, Any]], auth: TokenInfo | None = None
    ) -> list[dict[str, Any]]:
        ids = [str(item.get("dataset_id") or "") for item in items]
        counts = self.packages.package_download_counts(ids)
        fav_counts = self.packages.package_favorite_counts(ids)
        uid = auth.user_id if auth is not None else None
        starred = self.packages.package_favorites_for_user(uid, ids) if uid else set()
        for item in items:
            did = str(item.get("dataset_id") or "")
            item["download_count"] = int(counts.get(did, 0))
            item["favorite_count"] = int(fav_counts.get(did, 0))
            item["favorited"] = did in starred
        return items

    def _apply_icons(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        icons = self.packages.package_icons()
        for item in items:
            pair = icons.get(str(item.get("dataset_id") or ""))
            if not pair:
                continue
            key, github = pair
            if key:
                item["icon_key"] = key
            if github:
                item["icon_github"] = github
        return items

    def publish(self, *, meta: dict[str, Any], archive: Path, auth: TokenInfo) -> dict[str, Any]:
        size_on_disk = archive.stat().st_size
        if size_on_disk > self.max_upload:
            raise RegistryAppError(
                "payload_too_large",
                f"max {self.max_upload} bytes",
                http_status=413,
            )
        dataset_id = str(meta.get("dataset_id") or "")
        version = str(meta.get("version") or "")
        package_digest = str(meta.get("package_digest") or "")
        blob_digest = str(meta.get("blob_digest") or "")
        media_type = str(meta.get("media_type") or "")
        visibility = str(meta.get("visibility") or "private")
        slot = str(meta.get("slot") or "").strip().casefold()
        raw_org = str(meta.get("org_id") or meta.get("org") or "").strip()
        org_id = raw_org.casefold() if raw_org else None
        size = int(meta.get("size") or size_on_disk)
        user_id = auth.user_id or ""
        if visibility not in {"private", "public"}:
            raise RegistryAppError("invalid_request", "bad visibility", http_status=400)
        package_kind = str(meta.get("package_kind") or "dataset").strip().casefold()
        leaf = dataset_id.rsplit("/", 1)[-1]
        if is_builtin_plugin_id(dataset_id) or (
            package_kind == "plugin" and is_builtin_plugin_id(leaf)
        ):
            raise RegistryAppError(
                "plugin_id_reserved",
                f"{leaf} ships with ageval; it is not a Hub package",
                http_status=400,
            )
        if package_kind == "agent":
            hit = reserved_harness_leaf(dataset_id)
            if hit is not None:
                raise RegistryAppError(
                    "agent_id_reserved",
                    f"{hit} ships with ageval; it is not a Hub package",
                    http_status=400,
                )
        if slot == DRAFT_SLOT or is_draft_version(version):
            return self.upsert_draft(meta=meta, archive=archive, auth=auth)
        if not org_id:
            raise RegistryAppError("org_required", "publish requires org_id", http_status=400)
        if self.orgs.get_org(org_id) is None:
            raise RegistryAppError("org_not_found", f"org {org_id!r} not found", http_status=400)
        if not AccessPolicy.is_admin(auth.scopes) and self.orgs.membership(org_id, user_id) is None:
            raise RegistryAppError(
                "forbidden",
                "must be org member to publish under this org",
                http_status=403,
            )
        actual_blob = sha256_file(archive)
        if actual_blob != blob_digest or size != size_on_disk:
            raise RegistryAppError(
                "digest_mismatch",
                "blob digest or size mismatch",
                http_status=400,
            )
        if package_kind not in {"dataset", "plugin", "agent"}:
            raise RegistryAppError(
                "invalid_request",
                "package_kind must be dataset, plugin or agent",
                http_status=400,
            )
        self._validate_archive(
            archive,
            package_kind=package_kind,
            media_type=media_type,
            package_digest=package_digest,
        )
        replace = bool(meta.get("replace")) or str(meta.get("replace") or "").lower() in {
            "1",
            "true",
            "yes",
        }
        existing_rel = self.packages.get_by_version(dataset_id, version)
        if existing_rel is not None:
            if not replace:
                raise RegistryAppError("conflict", "release already exists", http_status=409)
            if not self._may_replace(existing_rel, auth):
                raise RegistryAppError("not_found", "release not found", http_status=404)
            self.packages.delete_release(dataset_id, version)
            self._gc_blob(existing_rel.blob_digest)
        row = ReleaseRow(
            dataset_id=dataset_id,
            version=version,
            visibility=visibility,
            package_digest=package_digest,
            blob_digest=blob_digest,
            size=size,
            media_type=media_type,
            created_at=now(),
            org_id=org_id,
            uploaded_by=auth.user_id or "",
        )
        try:
            self.blobs.put_if_absent(blob_digest, archive, prefix="packages")
            self.packages.insert(row)
        except ValueError as exc:
            raise RegistryAppError("conflict", "release already exists", http_status=409) from exc
        self._store_task_summary(archive, package_digest)
        if existing_rel is not None and existing_rel.package_digest != package_digest:
            self._gc_task_summary(existing_rel.package_digest)
        payload = self._with_download_count(release_to_dict(row), auth)
        if existing_rel is not None and replace:
            payload["replaced"] = True
        return payload

    def upsert_draft(
        self, *, meta: dict[str, Any], archive: Path, auth: TokenInfo
    ) -> dict[str, Any]:
        size_on_disk = archive.stat().st_size
        if size_on_disk > self.max_upload:
            raise RegistryAppError(
                "payload_too_large",
                f"max {self.max_upload} bytes",
                http_status=413,
            )
        dataset_id = str(meta.get("dataset_id") or "")
        package_digest = str(meta.get("package_digest") or "")
        blob_digest = str(meta.get("blob_digest") or "")
        media_type = str(meta.get("media_type") or "")
        visibility = str(meta.get("visibility") or "private")
        raw_org = str(meta.get("org_id") or meta.get("org") or "").strip()
        org_id = raw_org.casefold() if raw_org else None
        size = int(meta.get("size") or size_on_disk)
        user_id = auth.user_id or ""
        if not dataset_id:
            raise RegistryAppError("invalid_request", "dataset_id required", http_status=400)
        if visibility not in {"private", "public"}:
            raise RegistryAppError("invalid_request", "bad visibility", http_status=400)
        if not org_id:
            raise RegistryAppError("org_required", "draft requires org_id", http_status=400)
        if self.orgs.get_org(org_id) is None:
            raise RegistryAppError("org_not_found", f"org {org_id!r} not found", http_status=400)
        package_kind = str(meta.get("package_kind") or "dataset").strip().casefold()
        if package_kind != "dataset":
            raise RegistryAppError(
                "invalid_request",
                "draft slot is only for dataset packages",
                http_status=400,
            )
        existing = self.packages.get_draft(dataset_id)
        if not self.access.can_write_draft(existing, org_id=org_id, auth=auth):
            raise RegistryAppError(
                "forbidden",
                "dataset collaborator or first-upload org member required",
                http_status=403,
            )
        actual_blob = sha256_file(archive)
        if actual_blob != blob_digest or size != size_on_disk:
            raise RegistryAppError(
                "digest_mismatch",
                "blob digest or size mismatch",
                http_status=400,
            )
        self._validate_archive(
            archive,
            package_kind="dataset",
            media_type=media_type,
            package_digest=package_digest,
        )
        old_blob = existing.blob_digest if existing else None
        row = DraftRow(
            dataset_id=dataset_id,
            org_id=org_id,
            visibility=visibility,
            package_digest=package_digest,
            blob_digest=blob_digest,
            size=size,
            media_type=media_type,
            package_kind="dataset",
            uploaded_by=user_id,
            updated_at=now(),
        )
        self.blobs.put_if_absent(blob_digest, archive, prefix="packages")
        stored = self.packages.upsert_draft(row)
        self._store_task_summary(archive, package_digest)
        if existing is None and user_id:
            self.packages.upsert_dataset_acl(dataset_id, user_id, role="owner")
        if existing is not None and existing.package_digest != package_digest:
            self._gc_task_summary(existing.package_digest)
        if old_blob and old_blob != blob_digest:
            self._gc_blob(old_blob)
        payload = self._with_download_count(release_to_dict(stored.as_release()), auth)
        payload["replaced"] = existing is not None
        return payload

    def release_draft(
        self,
        *,
        dataset_id: str,
        auth: TokenInfo,
        visibility: str | None = None,
        replace: bool = False,
        version: str | None = None,
    ) -> dict[str, Any]:
        draft = self.packages.get_draft(dataset_id)
        if draft is None or not self.access.can_release_draft(draft, auth):
            raise RegistryAppError("not_found", "draft not found", http_status=404)
        archive = read_blob(self.blobs, draft.blob_digest, prefix="packages")
        if archive is None:
            raise RegistryAppError("not_found", "draft blob missing", http_status=404)
        rel_version = (version or "").strip() or self._version_from_archive(archive)
        if not rel_version or is_draft_version(rel_version):
            raise RegistryAppError(
                "invalid_request",
                "release version is required and cannot be 'draft'",
                http_status=400,
            )
        vis = visibility or draft.visibility
        if vis not in {"private", "public"}:
            raise RegistryAppError("invalid_request", "bad visibility", http_status=400)
        existing_rel = self.packages.get_by_version(dataset_id, rel_version)
        if existing_rel is not None:
            if not replace:
                raise RegistryAppError("conflict", "release already exists", http_status=409)
            if not self._may_replace(existing_rel, auth):
                raise RegistryAppError("not_found", "release not found", http_status=404)
            self.packages.delete_release(dataset_id, rel_version)
            self._gc_blob(existing_rel.blob_digest)
        row = ReleaseRow(
            dataset_id=dataset_id,
            version=rel_version,
            visibility=vis,
            package_digest=draft.package_digest,
            blob_digest=draft.blob_digest,
            size=draft.size,
            media_type=draft.media_type,
            created_at=now(),
            org_id=draft.org_id,
            uploaded_by=draft.uploaded_by or auth.user_id or "",
        )
        try:
            self.packages.insert(row)
        except ValueError as exc:
            raise RegistryAppError("conflict", "release already exists", http_status=409) from exc
        payload = self._with_download_count(release_to_dict(row), auth)
        if existing_rel is not None and replace:
            payload["replaced"] = True
        payload["from_draft"] = True
        return payload

    def list_packages(
        self,
        *,
        auth: TokenInfo,
        prefix: str | None,
        visibility: str | None,
        version: str | None,
        package_kind: str | None,
        mine: bool = False,
        favorited: bool = False,
        orgs: bool = False,
    ) -> dict[str, Any]:
        if visibility is not None and visibility not in {"public", "private"}:
            raise RegistryAppError("invalid_request", "bad visibility", http_status=400)
        if package_kind is not None and package_kind not in {"dataset", "plugin", "agent"}:
            raise RegistryAppError(
                "invalid_request",
                "package_kind must be dataset, plugin or agent",
                http_status=400,
            )
        rows = self.packages.list_releases(
            dataset_id_prefix=prefix or None,
            visibility=visibility,
            version=version or None,
            include_private=True,
        )
        items = [release_to_dict(r) for r in rows if self.access.visible_package(r, auth)]
        if package_kind in (None, "dataset"):
            for draft in self.packages.list_drafts():
                if not self.access.entitled_to_draft(draft, auth):
                    continue
                if prefix and not draft.dataset_id.startswith(prefix):
                    continue
                if visibility in {"public", "private"} and draft.visibility != visibility:
                    continue
                items.append(release_to_dict(draft.as_release()))
        if package_kind is not None:
            items = [i for i in items if i.get("package_kind") == package_kind]
        if mine:
            items = self._filter_mine(items, auth)
        if orgs:
            items = self._filter_orgs(items, auth)
        labels = self.packages.package_display_names()
        for item in items:
            label = labels.get(str(item.get("dataset_id") or ""))
            if label:
                item["display_name"] = label
        self._apply_icons(items)
        self._with_download_counts(items, auth=auth)
        self._attach_task_counts(items)
        self._apply_description_overrides(items)
        if favorited:
            items = [i for i in items if i.get("favorited")]
        explore = not mine and not orgs and not favorited and visibility != "private"
        if package_kind == "plugin" and explore:
            items = builtin_plugin_items(prefix=prefix) + items
        if package_kind == "agent" and explore:
            items = builtin_agent_items(prefix=prefix) + items
        return {"items": items}

    def _attach_task_counts(self, items: list[dict[str, Any]]) -> None:
        digests = [
            str(item.get("package_digest") or "")
            for item in items
            if item.get("package_kind") == "dataset"
        ]
        counts = self.packages.package_task_counts(digests)
        descriptions = self.packages.package_manifest_descriptions(digests)
        for item in items:
            if item.get("package_kind") != "dataset":
                continue
            digest = str(item.get("package_digest") or "")
            item["task_count"] = counts.get(digest, 0)
            description = descriptions.get(digest)
            if description:
                item["description"] = description

    def _apply_description_overrides(self, items: list[dict[str, Any]]) -> None:
        overrides = self.packages.package_descriptions()
        if not overrides:
            return
        for item in items:
            override = overrides.get(str(item.get("dataset_id") or ""))
            if override:
                item["description"] = override

    def _effective_description(self, dataset_id: str, package_digest: str) -> str:
        override = self.packages.get_package_description(dataset_id)
        if override:
            return override
        manifest = self.packages.package_manifest_descriptions([package_digest])
        return manifest.get(package_digest, "")

    def _filter_orgs(self, items: list[dict[str, Any]], auth: TokenInfo) -> list[dict[str, Any]]:
        """Keep packages published by organizations the caller belongs to."""
        uid = auth.user_id or ""
        if not uid:
            return []
        org_ids = self.orgs.user_org_ids(uid)
        return [item for item in items if str(item.get("org_id") or "") in org_ids]

    def _filter_mine(self, items: list[dict[str, Any]], auth: TokenInfo) -> list[dict[str, Any]]:
        """Keep packages the caller uploaded or can maintain (ACL)."""
        uid = auth.user_id or ""
        if not uid:
            return []
        maintainable = {
            row.dataset_id
            for row in self.packages.list_dataset_acl_for_user(uid)
            if row.role in {"owner", "collaborator"}
        }
        out: list[dict[str, Any]] = []
        for item in items:
            uploader = str(item.get("uploaded_by") or "")
            dataset_id = str(item.get("dataset_id") or "")
            kind = str(item.get("package_kind") or "")
            if uploader and uploader == uid:
                out.append(item)
                continue
            if kind == "dataset" and dataset_id in maintainable:
                out.append(item)
        return out

    def list_versions(
        self,
        *,
        dataset_id: str,
        auth: TokenInfo,
        package_kind: str | None = None,
    ) -> dict[str, Any]:
        kind = overlay_kind(dataset_id, package_kind)
        if kind is not None:
            builtin = _builtin_item(dataset_id, kind)
            return {"dataset_id": builtin["dataset_id"], "items": [builtin]}
        rows = self.packages.list_versions(dataset_id, include_private=True)
        items = [release_to_dict(r) for r in rows if self.access.visible_package(r, auth)]
        draft = self.packages.get_draft(dataset_id)
        if draft is not None and self.access.entitled_to_draft(draft, auth):
            items.insert(0, release_to_dict(draft.as_release()))
        label = self.packages.get_package_display_name(dataset_id)
        if label:
            for item in items:
                item["display_name"] = label
        self._apply_icons(items)
        self._with_download_counts(items, auth=auth)
        self._attach_task_counts(items)
        self._apply_description_overrides(items)
        return {"dataset_id": dataset_id, "items": items}

    def serve_meta(
        self,
        *,
        dataset_id: str,
        version: str | None,
        package_digest: str | None,
        auth: TokenInfo,
        package_kind: str | None = None,
    ) -> dict[str, Any]:
        kind = overlay_kind(dataset_id, package_kind)
        if kind is not None:
            if package_digest:
                raise RegistryAppError("not_found", f"builtin {kind} has no blob", http_status=404)
            if version:
                raise RegistryAppError(
                    "not_found", f"builtin {kind} has no version", http_status=404
                )
            return _builtin_item(dataset_id, kind)
        row = self._visible_release(
            dataset_id=dataset_id,
            auth=auth,
            package_digest=package_digest,
            version=version,
        )
        payload = self._with_download_count(release_to_dict(row), auth)
        label = self.packages.get_package_display_name(dataset_id)
        if label:
            payload["display_name"] = label
        self._apply_icons([payload])
        description_value = self._effective_description(dataset_id, str(row.package_digest))
        if description_value:
            payload["description"] = description_value
        try:
            kind = package_kind_for_media_type(row.media_type)
        except ValueError as exc:
            raise RegistryAppError("invalid_format", str(exc), http_status=400) from exc
        payload["package_kind"] = kind
        if kind == "plugin":
            data = read_blob(self.blobs, row.blob_digest, prefix="packages")
            if data is not None:
                with contextlib.suppress(Exception):
                    payload["plugin_preview"] = _plugin_preview_from_archive(data)
        elif kind == "agent":
            data = read_blob(self.blobs, row.blob_digest, prefix="packages")
            if data is not None:
                with contextlib.suppress(Exception):
                    payload["agent_preview"] = _agent_preview_from_archive(data)
        return payload

    def serve_content(
        self,
        *,
        dataset_id: str,
        package_digest: str,
        auth: TokenInfo,
    ) -> tuple[Any, int, ReleaseRow]:
        row = self._visible_release(
            dataset_id=dataset_id,
            auth=auth,
            package_digest=package_digest,
        )
        size = self.blobs.size(row.blob_digest, prefix="packages")
        fh = self.blobs.open(row.blob_digest, prefix="packages")
        if fh is None or size is None:
            raise RegistryAppError("not_found", "blob missing", http_status=404)
        self.packages.increment_package_download(row.dataset_id)
        return fh, int(size), row

    def list_files(
        self,
        *,
        dataset_id: str,
        auth: TokenInfo,
        package_digest: str | None = None,
        version: str | None = None,
        package_kind: str | None = None,
    ) -> dict[str, Any]:
        from services.registry.builtin_plugins import builtin_list_files
        from services.registry.package_files import get_or_build_index

        kind = overlay_kind(dataset_id, package_kind)
        if kind == "plugin":
            return builtin_list_files(dataset_id)
        if kind == "agent":
            return builtin_agent_list_files(dataset_id)

        row = self._visible_release(
            dataset_id=dataset_id,
            auth=auth,
            package_digest=package_digest,
            version=version,
        )
        archive = read_blob(self.blobs, row.blob_digest, prefix="packages")
        if archive is None:
            raise RegistryAppError("not_found", "blob missing", http_status=404)
        try:
            index = get_or_build_index(archive, package_digest=row.package_digest)
        except Exception as exc:  # noqa: BLE001
            raise RegistryAppError(
                "archive_error",
                f"cannot index package: {exc}",
                http_status=500,
            ) from exc
        return {
            "dataset_id": row.dataset_id,
            "digest": row.package_digest,
            "version": row.version,
            "items": index.list_items(),
        }

    def list_tasks(
        self,
        *,
        dataset_id: str,
        auth: TokenInfo,
        package_digest: str | None = None,
        version: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        q: str | None = None,
    ) -> dict[str, Any]:
        row = self._visible_release(
            dataset_id=dataset_id,
            auth=auth,
            package_digest=package_digest,
            version=version,
        )
        summary = self.packages.get_package_task_summary(row.package_digest)
        if summary is None:
            summary = self._backfill_task_summary(row.package_digest, row.blob_digest)
        tasks, has_shared, overlay_prefixes = summary
        needle = (q or "").strip().casefold()
        if needle:
            tasks = [item for item in tasks if needle in str(item.get("task_id") or "").casefold()]
        page, total = page_slice(tasks, limit=limit, offset=offset)
        self._attach_task_job_stats(page, dataset_id=row.dataset_id, auth=auth)
        return {
            "dataset_id": row.dataset_id,
            "digest": row.package_digest,
            "version": row.version,
            "items": page,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_shared": has_shared,
            "overlay_prefixes": overlay_prefixes,
        }

    def read_file(
        self,
        *,
        dataset_id: str,
        file_path: str,
        auth: TokenInfo,
        package_digest: str | None = None,
        version: str | None = None,
        package_kind: str | None = None,
    ) -> dict[str, Any]:
        from services.registry.builtin_plugins import builtin_read_file
        from services.registry.package_files import (
            MAX_FILE_BYTES,
            PackageFileNotFound,
            PackageFileTooLarge,
            PackagePathError,
            file_payload,
            normalize_package_path,
            read_member,
        )

        kind = overlay_kind(dataset_id, package_kind)
        if kind == "plugin":
            return builtin_read_file(dataset_id, file_path)
        if kind == "agent":
            return builtin_agent_read_file(dataset_id, file_path)

        row = self._visible_release(
            dataset_id=dataset_id,
            auth=auth,
            package_digest=package_digest,
            version=version,
        )
        try:
            safe_path = normalize_package_path(file_path)
        except PackagePathError as exc:
            raise RegistryAppError("invalid_path", str(exc), http_status=400) from exc
        archive = read_blob(self.blobs, row.blob_digest, prefix="packages")
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
                "payload_too_large",
                f"file exceeds {MAX_FILE_BYTES} bytes (path={exc.path}, size={exc.size})",
                http_status=413,
                extra={"max_bytes": MAX_FILE_BYTES, "path": exc.path, "size": exc.size},
            ) from exc
        return file_payload(safe_path, data, size=size, truncated=truncated)

    def delete_release(self, *, dataset_id: str, version: str, auth: TokenInfo) -> dict[str, Any]:
        row = self.packages.get_by_version(dataset_id, version)
        if row is None or not self.can_manage(row, auth):
            raise RegistryAppError("not_found", "release not found", http_status=404)
        self.packages.delete_release(dataset_id, version)
        blob_deleted = self._gc_blob(row.blob_digest)
        return {
            "ok": True,
            "dataset_id": dataset_id,
            "version": version,
            "blob_deleted": blob_deleted,
        }

    def patch_display_name(
        self, *, dataset_id: str, display_name: object, auth: TokenInfo
    ) -> dict[str, Any]:
        return self.patch_marketplace(
            dataset_id=dataset_id,
            auth=auth,
            display_name=display_name,
            has_display_name=True,
        )

    def patch_marketplace(
        self,
        *,
        dataset_id: str,
        auth: TokenInfo,
        display_name: object = None,
        icon_key: object = None,
        icon_github: object = None,
        description: object = None,
        has_display_name: bool = False,
        has_icon_key: bool = False,
        has_icon_github: bool = False,
        has_description: bool = False,
    ) -> dict[str, Any]:
        row = self._latest_managed_release(dataset_id, auth)
        next_name: str | None = None
        next_key: str | None = None
        next_github: str | None = None
        next_description: str | None = None
        if has_display_name:
            next_name = _normalize_plugin_name_segment(dataset_id, display_name)
        if has_icon_key:
            next_key = normalize_icon_key(icon_key)
        if has_icon_github:
            next_github = normalize_icon_github(icon_github)
        if has_description:
            next_description = _normalize_marketplace_description(description)
        stored_name = None
        if next_name is not None:
            stored_name = self.packages.set_package_display_name(dataset_id, next_name)
        if has_icon_key or has_icon_github:
            cur_key, cur_github = self.packages.get_package_icon(dataset_id)
            key = next_key if has_icon_key else cur_key
            github = next_github if has_icon_github else cur_github
            if has_icon_key and has_icon_github:
                key, github = next_key or "", next_github or ""
            self.packages.set_package_icon(dataset_id, icon_key=key or "", icon_github=github or "")
        if has_description:
            self.packages.set_package_description(dataset_id, next_description or "")
        payload = self._with_download_count(release_to_dict(row), auth)
        label = (
            stored_name
            if stored_name is not None
            else self.packages.get_package_display_name(dataset_id)
        )
        if label:
            payload["display_name"] = label
        self._apply_icons([payload])
        description_value = self._effective_description(
            dataset_id, str(payload.get("package_digest") or "")
        )
        if description_value:
            payload["description"] = description_value
        return payload

    def _latest_managed_release(self, dataset_id: str, auth: TokenInfo) -> Any:
        rows = self.packages.list_releases(
            dataset_id_prefix=dataset_id,
            include_private=True,
        )
        owned = [r for r in rows if r.dataset_id == dataset_id and self.can_manage(r, auth)]
        if not owned:
            draft = self.packages.get_draft(dataset_id)
            if draft is not None and self.access.can_write_draft(
                draft, org_id=draft.org_id, auth=auth
            ):
                return draft.as_release()
            raise RegistryAppError("forbidden", "org owner required", http_status=403)
        owned.sort(key=lambda r: r.created_at, reverse=True)
        return owned[0]

    def patch_visibility(
        self, *, dataset_id: str, version: str, visibility: str, auth: TokenInfo
    ) -> dict[str, Any]:
        row = self.packages.get_by_version(dataset_id, version)
        if row is None or not self.can_manage(row, auth):
            raise RegistryAppError("not_found", "release not found", http_status=404)
        if visibility not in {"public", "private"}:
            raise RegistryAppError(
                "invalid_request",
                "visibility must be public or private",
                http_status=400,
            )
        try:
            updated = self.packages.set_release_visibility(dataset_id, version, visibility)
        except LookupError as exc:
            raise RegistryAppError("not_found", "release not found", http_status=404) from exc
        return self._with_download_count(release_to_dict(updated), auth)

    def set_favorite(self, *, dataset_id: str, auth: TokenInfo, favorited: bool) -> dict[str, Any]:
        if not auth.user_id:
            raise RegistryAppError("unauthorized", "login required", http_status=401)
        row = self._latest_visible_release(dataset_id, auth)
        try:
            kind = package_kind_for_media_type(row.media_type)
        except ValueError as exc:
            raise RegistryAppError("invalid_format", str(exc), http_status=400) from exc
        if kind not in {"plugin", "agent"}:
            raise RegistryAppError(
                "invalid_request",
                "only plugin and agent packages can be favorited",
                http_status=400,
            )
        if favorited:
            self.packages.add_package_favorite(auth.user_id, row.dataset_id)
        else:
            self.packages.remove_package_favorite(auth.user_id, row.dataset_id)
        counts = self.packages.package_favorite_counts([row.dataset_id])
        starred = self.packages.package_favorites_for_user(auth.user_id, [row.dataset_id])
        return {
            "dataset_id": row.dataset_id,
            "package_kind": kind,
            "favorite_count": int(counts.get(row.dataset_id, 0)),
            "favorited": row.dataset_id in starred,
        }

    def _latest_visible_release(self, dataset_id: str, auth: TokenInfo) -> ReleaseRow:
        rows = [
            r
            for r in self.packages.list_versions(dataset_id, include_private=True)
            if r.dataset_id == dataset_id and self.access.visible_package(r, auth)
        ]
        if rows:
            rows.sort(key=lambda r: r.created_at, reverse=True)
            return rows[0]
        draft = self.packages.get_draft(dataset_id)
        if draft is not None and self.access.entitled_to_draft(draft, auth):
            return draft.as_release()
        raise RegistryAppError("not_found", "package not found", http_status=404)

    def _visible_release(
        self,
        *,
        dataset_id: str,
        auth: TokenInfo,
        package_digest: str | None = None,
        version: str | None = None,
    ) -> ReleaseRow:
        draft: DraftRow | None = None
        if package_digest:
            row = self.packages.get_by_digest(dataset_id, package_digest)
            if row is None:
                draft = self.packages.get_draft_by_digest(dataset_id, package_digest)
        elif version:
            if is_draft_version(version):
                draft = self.packages.get_draft(dataset_id)
                row = None
            else:
                row = self.packages.get_by_version(dataset_id, version)
        else:
            row = None
        if draft is not None:
            if not self.access.entitled_to_draft(draft, auth):
                raise RegistryAppError("not_found", "release not found", http_status=404)
            return draft.as_release()
        if row is None or not self.access.visible_package(row, auth):
            raise RegistryAppError("not_found", "release not found", http_status=404)
        return row

    def _version_from_archive(self, archive: bytes) -> str:
        from ageval.config.dataset import load_dataset_manifest
        from ageval.registry.archive import extract_archive

        try:
            with tempfile.TemporaryDirectory(prefix="ageval-rel-") as tmp:
                extract_archive(archive, Path(tmp))
                man = load_dataset_manifest(Path(tmp))
                return str(man.version or "").strip()
        except Exception as exc:  # noqa: BLE001
            raise RegistryAppError(
                "invalid_archive",
                f"cannot read draft version: {exc}",
                http_status=400,
            ) from exc

    def _may_replace(self, existing: ReleaseRow, auth: TokenInfo) -> bool:
        if AccessPolicy.is_admin(auth.scopes):
            return True
        if not auth.user_id or not existing.org_id:
            return False
        mem = self.orgs.membership(existing.org_id, auth.user_id)
        return mem is not None and mem.role == "owner"

    def _gc_blob(self, blob_digest: str) -> bool:
        if not blob_digest:
            return False
        if self.packages.count_package_blob_refs(blob_digest) > 0:
            return False
        return bool(self.blobs.delete(blob_digest, prefix="packages"))

    def _store_task_summary(self, archive: Path, package_digest: str) -> None:
        from services.registry.package_files import build_index_from_archive

        index = build_index_from_archive(archive.read_bytes(), package_digest=package_digest)
        tasks, has_shared = index.list_tasks()
        self.packages.put_package_task_summary(
            package_digest,
            has_shared=has_shared,
            tasks=tasks,
            overlay_prefixes=index.overlay_prefixes,
            description=index.description,
        )

    def _backfill_task_summary(
        self, package_digest: str, blob_digest: str
    ) -> tuple[list[dict[str, Any]], bool, list[str]]:
        from services.registry.package_files import get_or_build_index

        archive = read_blob(self.blobs, blob_digest, prefix="packages")
        if archive is None:
            raise RegistryAppError("not_found", "blob missing", http_status=404)
        try:
            index = get_or_build_index(archive, package_digest=package_digest)
        except Exception as exc:  # noqa: BLE001
            raise RegistryAppError(
                "archive_error",
                f"cannot index package: {exc}",
                http_status=500,
            ) from exc
        tasks, has_shared = index.list_tasks()
        self.packages.put_package_task_summary(
            package_digest,
            has_shared=has_shared,
            tasks=tasks,
            overlay_prefixes=index.overlay_prefixes,
            description=index.description,
        )
        return tasks, has_shared, index.overlay_prefixes

    def _gc_task_summary(self, package_digest: str) -> None:
        if not package_digest:
            return
        if self.packages.count_package_digest_refs(package_digest) > 0:
            return
        self.packages.delete_package_task_summary(package_digest)

    def _attach_task_job_stats(
        self,
        page: list[dict[str, Any]],
        *,
        dataset_id: str,
        auth: TokenInfo,
    ) -> None:
        from services.registry.dataset import parse_task_refs

        if not page:
            return
        wanted = {str(item.get("task_id") or "") for item in page}
        wanted.discard("")
        hits: dict[str, list[tuple[float, str | None, float | None]]] = {
            task_id: [] for task_id in wanted
        }
        for row in self.packages.list_suite_task_refs(dataset_id):
            if not self.access.visible_result(
                result_kind="suite",
                result_id=str(row.get("suite_run_id") or ""),
                visibility=str(row.get("visibility") or ""),
                uploaded_by=str(row.get("uploaded_by") or ""),
                auth=auth,
            ):
                continue
            created = float(row.get("created_at") or 0)
            for ref in parse_task_refs(row.get("tasks_json")):
                task_id = str(ref.get("task_id") or "").strip()
                if task_id not in hits:
                    continue
                status = str(ref.get("status") or "").strip() or None
                raw_score = ref.get("score")
                score = raw_score if isinstance(raw_score, (int, float)) else None
                hits[task_id].append((created, status, score))
        for item in page:
            task_id = str(item.get("task_id") or "")
            found = hits.get(task_id) or []
            found.sort(key=lambda row: row[0], reverse=True)
            last = found[0] if found else None
            item["job_count"] = len(found)
            item["last_status"] = last[1] if last else None
            item["last_score"] = last[2] if last else None

    def _validate_archive(
        self,
        archive: Path,
        *,
        package_kind: str,
        media_type: str,
        package_digest: str,
    ) -> None:
        from ageval.registry.archive import extract_archive
        from ageval.registry.digest import compute_package_digest
        from ageval.registry.media_types import DATASET_MEDIA_TYPE
        from ageval.registry.plugin_package import (
            PLUGIN_MEDIA_TYPE,
            assert_plugin_package,
            compute_plugin_digest,
        )

        try:
            with tempfile.TemporaryDirectory(prefix="ageval-reg-") as tmp:
                extract_archive(archive, Path(tmp))
                tmp_path = Path(tmp)
                if package_kind == "plugin":
                    if media_type != PLUGIN_MEDIA_TYPE:
                        raise RegistryAppError(
                            "invalid_format",
                            f"plugin media_type must be {PLUGIN_MEDIA_TYPE}",
                            http_status=400,
                        )
                    try:
                        assert_plugin_package(tmp_path)
                    except RegistryAppError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        raise RegistryAppError(
                            "invalid_format",
                            f"not a valid ageval.plugin/1: {exc}",
                            http_status=400,
                        ) from exc
                    if (tmp_path / "ageval.yaml").is_file() and not (
                        (tmp_path / "plugin.yaml").is_file()
                        or (tmp_path / "ageval.plugin.yaml").is_file()
                    ):
                        raise RegistryAppError(
                            "invalid_format",
                            "dataset package cannot be published as plugin",
                            http_status=400,
                        )
                    got = compute_plugin_digest(tmp_path)
                elif package_kind == "agent":
                    from ageval.registry.agent_package import (
                        AGENT_MEDIA_TYPE,
                        assert_agent_package,
                        compute_agent_digest,
                    )

                    if media_type != AGENT_MEDIA_TYPE:
                        raise RegistryAppError(
                            "invalid_format",
                            f"agent media_type must be {AGENT_MEDIA_TYPE}",
                            http_status=400,
                        )
                    try:
                        assert_agent_package(tmp_path)
                    except RegistryAppError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        raise RegistryAppError(
                            "invalid_format",
                            f"not a valid ageval.agent/1: {exc}",
                            http_status=400,
                        ) from exc
                    got = compute_agent_digest(tmp_path)
                else:
                    if media_type != DATASET_MEDIA_TYPE:
                        raise RegistryAppError(
                            "invalid_format",
                            f"dataset media_type must be {DATASET_MEDIA_TYPE}",
                            http_status=400,
                        )
                    if (
                        (tmp_path / "plugin.yaml").is_file()
                        or (tmp_path / "ageval.plugin.yaml").is_file()
                    ) and not (tmp_path / "ageval.yaml").is_file():
                        raise RegistryAppError(
                            "invalid_format",
                            "plugin package must use package_kind=plugin",
                            http_status=400,
                        )
                    if (tmp_path / "agent.yaml").is_file() and not (
                        tmp_path / "ageval.yaml"
                    ).is_file():
                        raise RegistryAppError(
                            "invalid_format",
                            "agent package must use package_kind=agent",
                            http_status=400,
                        )
                    got = compute_package_digest(tmp_path)
                if got != package_digest:
                    raise RegistryAppError(
                        "digest_mismatch",
                        "package digest mismatch after extract",
                        http_status=400,
                    )
        except RegistryAppError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RegistryAppError("invalid_archive", str(exc), http_status=400) from exc


def _agent_preview_from_archive(archive: bytes) -> dict[str, Any]:
    """Secret-free agent detail preview (design/14): manifest + binding + files."""
    from ageval.agents.manifest import load_agent_manifest
    from ageval.config.profiles import project_job_overlay
    from ageval.registry.archive import extract_archive

    with tempfile.TemporaryDirectory(prefix="ageval-prev-") as tmp:
        root = Path(tmp)
        extract_archive(archive, root)
        man = load_agent_manifest(root)
        files = sorted(
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )
        overlay = project_job_overlay({"agent": man.binding}, environment="local")
        return {
            "agent_id": man.agent_id,
            "version": man.version,
            "format": "ageval.agent/1",
            "label": man.label,
            "description": man.description,
            "tags": list(man.tags),
            "binding": overlay["agent_profiles"].get("agent", {}),
            "files": files[:200],
        }


def _plugin_preview_from_archive(archive: bytes) -> dict[str, Any]:
    from ageval.plugins.manifest import load_manifest
    from ageval.registry.archive import extract_archive

    with tempfile.TemporaryDirectory(prefix="ageval-prev-") as tmp:
        root = Path(tmp)
        extract_archive(archive, root)
        man = load_manifest(root)
        files = sorted(
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )
        declared: list[dict[str, Any]] = []
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
        preview: dict[str, Any] = {
            "plugin_id": man.plugin_id,
            "version": man.version,
            "format": man.format,
            "slots": man.slots_summary(),
            "declared": declared,
            "files": files[:200],
        }
        if man.description:
            preview["description"] = man.description
        return preview
