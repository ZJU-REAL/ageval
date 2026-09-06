"""Package aggregate: releases, drafts, dataset ACL, task summaries, downloads, favorites."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from services.registry import queries as Q
from services.registry.clock import now
from services.registry.protocols import PackageStoreProtocol
from services.registry.rows import (
    DatasetAclRow,
    DraftRow,
    ReleaseRow,
)
from services.registry.tokens import _normalize_user_id


class PackageStore(PackageStoreProtocol):
    """Package aggregate: releases, drafts, dataset ACL, task summaries, downloads, favorites."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def _connect(self) -> Any:
        return self._adapter.connect()

    def _exec(self, conn: Any, sql: str, params: Any = ()) -> Any:
        return self._adapter.execute(conn, sql, params)

    def insert(self, row: ReleaseRow) -> None:
        with self._connect() as conn:
            try:
                self._exec(
                    conn,
                    Q.INSERT_RELEASE,
                    (
                        row.dataset_id,
                        row.version,
                        row.visibility,
                        row.package_digest,
                        row.blob_digest,
                        row.size,
                        row.media_type,
                        row.created_at,
                        row.org_id,
                        row.uploaded_by or "",
                    ),
                )
                conn.commit()
            except self._adapter.integrity_error as exc:
                raise ValueError("release already exists") from exc

    def get_by_version(self, dataset_id: str, version: str) -> ReleaseRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_RELEASE_BY_VERSION, (dataset_id, version))
            r = cur.fetchone()
            return self._release_row(r) if r else None

    def get_by_digest(self, dataset_id: str, package_digest: str) -> ReleaseRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_RELEASE_BY_DIGEST, (dataset_id, package_digest))
            r = cur.fetchone()
            return self._release_row(r) if r else None

    def list_releases(
        self,
        *,
        dataset_id_prefix: str | None = None,
        visibility: str | None = None,
        version: str | None = None,
        include_private: bool = False,
    ) -> list[ReleaseRow]:
        sql, params = Q.list_releases_query(
            dataset_id_prefix=dataset_id_prefix,
            visibility=visibility,
            version=version,
            include_private=include_private,
        )
        with self._connect() as conn:
            cur = self._exec(conn, sql, params)
            return [self._release_row(r) for r in cur.fetchall()]

    def list_versions(self, dataset_id: str, *, include_private: bool = False) -> list[ReleaseRow]:
        sql, params = Q.list_versions_query(dataset_id, include_private=include_private)
        with self._connect() as conn:
            cur = self._exec(conn, sql, params)
            return [self._release_row(r) for r in cur.fetchall()]

    def count_package_blob_refs(self, blob_digest: str) -> int:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.COUNT_PACKAGE_BLOB_REFS,
                (blob_digest,),
            )
            n = int(cur.fetchone()["n"])
            cur_d = self._exec(conn, Q.COUNT_DRAFT_BLOB_REFS, (blob_digest,))
            return n + int(cur_d.fetchone()["n"])

    def put_package_task_summary(
        self,
        package_digest: str,
        *,
        has_shared: bool,
        tasks: list[dict[str, Any]],
        overlay_prefixes: list[str],
        description: str = "",
    ) -> None:
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPSERT_PACKAGE_TASK_SUMMARY,
                (
                    package_digest,
                    1 if has_shared else 0,
                    json.dumps(tasks),
                    json.dumps(overlay_prefixes),
                    description,
                    now(),
                ),
            )
            conn.commit()

    def package_task_counts(self, digests: list[str]) -> dict[str, int]:
        unique = [digest for digest in dict.fromkeys(digests) if digest]
        if not unique:
            return {}
        placeholders = ",".join("?" * len(unique))
        sql = (
            "SELECT package_digest, tasks_json FROM package_task_summaries "
            f"WHERE package_digest IN ({placeholders})"
        )
        out: dict[str, int] = {}
        with self._connect() as conn:
            cur = self._exec(conn, sql, tuple(unique))
            rows = cur.fetchall()
        for row in rows:
            try:
                tasks = json.loads(row["tasks_json"])
            except (TypeError, json.JSONDecodeError, KeyError):
                continue
            if not isinstance(tasks, list):
                continue
            out[str(row["package_digest"])] = sum(1 for item in tasks if isinstance(item, dict))
        return out

    def package_manifest_descriptions(self, digests: list[str]) -> dict[str, str]:
        unique = [digest for digest in dict.fromkeys(digests) if digest]
        if not unique:
            return {}
        placeholders = ",".join("?" * len(unique))
        sql = (
            "SELECT package_digest, description FROM package_task_summaries "
            f"WHERE package_digest IN ({placeholders}) "
            "AND description != ''"
        )
        with self._connect() as conn:
            cur = self._exec(conn, sql, tuple(unique))
            rows = cur.fetchall()
        return {str(row["package_digest"]): str(row["description"]) for row in rows}

    def get_package_task_summary(
        self, package_digest: str
    ) -> tuple[list[dict[str, Any]], bool, list[str]] | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_PACKAGE_TASK_SUMMARY, (package_digest,))
            row = cur.fetchone()
        if row is None:
            return None
        prefixes_raw = row["overlay_prefixes_json"]
        if prefixes_raw is None:
            return None
        try:
            tasks = json.loads(row["tasks_json"])
            prefixes = json.loads(prefixes_raw)
        except (TypeError, json.JSONDecodeError, KeyError):
            return None
        if not isinstance(tasks, list) or not isinstance(prefixes, list):
            return None
        items = [item for item in tasks if isinstance(item, dict)]
        overlay_prefixes = [str(item) for item in prefixes if isinstance(item, str)]
        return items, bool(int(row["has_shared"] or 0)), overlay_prefixes

    def delete_package_task_summary(self, package_digest: str) -> None:
        with self._connect() as conn:
            self._exec(conn, Q.DELETE_PACKAGE_TASK_SUMMARY, (package_digest,))
            conn.commit()

    def count_package_digest_refs(self, package_digest: str) -> int:
        with self._connect() as conn:
            cur = self._exec(conn, Q.COUNT_PACKAGE_DIGEST_REFS, (package_digest, package_digest))
            return int(cur.fetchone()["n"])

    def list_suite_task_refs(self, dataset_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_SUITE_TASK_REFS, (dataset_id,))
            return [dict(r) for r in cur.fetchall()]

    def delete_release(self, dataset_id: str, version: str) -> ReleaseRow:
        row = self.get_by_version(dataset_id, version)
        if row is None:
            raise LookupError("release not found")
        with self._connect() as conn:
            self._exec(
                conn,
                Q.DELETE_RELEASE,
                (dataset_id, version),
            )
            conn.commit()
        return row

    def set_release_visibility(self, dataset_id: str, version: str, visibility: str) -> ReleaseRow:
        if visibility not in {"public", "private"}:
            raise ValueError("bad visibility")
        row = self.get_by_version(dataset_id, version)
        if row is None:
            raise LookupError("release not found")
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPDATE_RELEASE_VISIBILITY,
                (visibility, dataset_id, version),
            )
            conn.commit()
        updated = self.get_by_version(dataset_id, version)
        assert updated is not None
        return updated

    def upsert_draft(self, row: DraftRow) -> DraftRow:
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPSERT_DRAFT,
                (
                    row.dataset_id,
                    row.org_id,
                    row.visibility,
                    row.package_digest,
                    row.blob_digest,
                    row.size,
                    row.media_type,
                    row.package_kind,
                    row.uploaded_by,
                    row.updated_at,
                ),
            )
            conn.commit()
        stored = self.get_draft(row.dataset_id)
        assert stored is not None
        return stored

    def get_draft(self, dataset_id: str) -> DraftRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_DRAFT, (dataset_id,))
            r = cur.fetchone()
            return self._draft_row(r) if r else None

    def get_draft_by_digest(self, dataset_id: str, package_digest: str) -> DraftRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_DRAFT_BY_DIGEST, (dataset_id, package_digest))
            r = cur.fetchone()
            return self._draft_row(r) if r else None

    def list_drafts(self) -> list[DraftRow]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.LIST_DRAFTS)
            return [self._draft_row(r) for r in cur.fetchall()]

    def delete_draft(self, dataset_id: str) -> DraftRow:
        row = self.get_draft(dataset_id)
        if row is None:
            raise LookupError("draft not found")
        with self._connect() as conn:
            self._exec(conn, Q.DELETE_DRAFT, (dataset_id,))
            conn.commit()
        return row

    def upsert_dataset_acl(
        self, dataset_id: str, user_id: str, *, role: str, created_at: float | None = None
    ) -> DatasetAclRow:
        ts = created_at if created_at is not None else now()
        with self._connect() as conn:
            self._exec(conn, Q.UPSERT_DATASET_ACL, (dataset_id, user_id, role, ts))
            conn.commit()
        row = self.dataset_acl(dataset_id, user_id)
        assert row is not None
        return row

    def dataset_acl(self, dataset_id: str, user_id: str) -> DatasetAclRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_DATASET_ACL, (dataset_id, user_id))
            r = cur.fetchone()
            return self._dataset_acl_row(r) if r else None

    def list_dataset_acl(self, dataset_id: str) -> list[DatasetAclRow]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.LIST_DATASET_ACL, (dataset_id,))
            return [self._dataset_acl_row(r) for r in cur.fetchall()]

    def list_dataset_acl_for_user(self, user_id: str) -> list[DatasetAclRow]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.LIST_DATASET_ACL_FOR_USER, (user_id,))
            return [self._dataset_acl_row(r) for r in cur.fetchall()]

    @staticmethod
    def _draft_row(r: sqlite3.Row) -> DraftRow:
        return DraftRow(
            dataset_id=str(r["dataset_id"]),
            org_id=str(r["org_id"] or ""),
            visibility=str(r["visibility"]),
            package_digest=str(r["package_digest"]),
            blob_digest=str(r["blob_digest"]),
            size=int(r["size"]),
            media_type=str(r["media_type"]),
            package_kind=str(r["package_kind"] or "dataset"),
            uploaded_by=str(r["uploaded_by"] or ""),
            updated_at=float(r["updated_at"]),
        )

    @staticmethod
    def _dataset_acl_row(r: sqlite3.Row) -> DatasetAclRow:
        return DatasetAclRow(
            dataset_id=str(r["dataset_id"]),
            user_id=str(r["user_id"]),
            role=str(r["role"]),
            created_at=float(r["created_at"]),
        )

    @staticmethod
    def _release_row(r: sqlite3.Row) -> ReleaseRow:
        keys = r.keys()
        org_id = r["org_id"] if "org_id" in keys else None
        uploaded_by = str(r["uploaded_by"]) if "uploaded_by" in keys and r["uploaded_by"] else ""
        return ReleaseRow(
            dataset_id=r["dataset_id"],
            version=r["version"],
            visibility=r["visibility"],
            package_digest=r["package_digest"],
            blob_digest=r["blob_digest"],
            size=int(r["size"]),
            media_type=r["media_type"],
            created_at=float(r["created_at"]),
            org_id=str(org_id) if org_id else None,
            uploaded_by=uploaded_by,
        )

    def set_package_display_name(self, dataset_id: str, display_name: str) -> str:
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPSERT_PACKAGE_DISPLAY_NAME,
                (dataset_id, display_name, now()),
            )
            conn.commit()
        return display_name

    def get_package_display_name(self, dataset_id: str) -> str:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_PACKAGE_DISPLAY_NAME, (dataset_id,))
            row = cur.fetchone()
        if row is None:
            return ""
        return str(row["display_name"] or "")

    def package_display_names(self) -> dict[str, str]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_PACKAGE_DISPLAY_NAMES)
            return {
                str(r["dataset_id"]): str(r["display_name"] or "")
                for r in cur.fetchall()
                if r["display_name"]
            }

    def set_package_description(self, dataset_id: str, description: str) -> str:
        with self._connect() as conn:
            if description:
                self._exec(
                    conn,
                    Q.UPSERT_PACKAGE_DESCRIPTION,
                    (dataset_id, description, now()),
                )
            else:
                self._exec(conn, Q.DELETE_PACKAGE_DESCRIPTION, (dataset_id,))
            conn.commit()
        return description

    def get_package_description(self, dataset_id: str) -> str:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_PACKAGE_DESCRIPTION, (dataset_id,))
            row = cur.fetchone()
        if row is None:
            return ""
        return str(row["description"] or "")

    def package_descriptions(self) -> dict[str, str]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_PACKAGE_DESCRIPTIONS)
            return {
                str(r["dataset_id"]): str(r["description"] or "")
                for r in cur.fetchall()
                if r["description"]
            }

    def set_package_icon(
        self, dataset_id: str, *, icon_key: str, icon_github: str
    ) -> tuple[str, str]:
        with self._connect() as conn:
            if icon_key or icon_github:
                self._exec(
                    conn,
                    Q.UPSERT_PACKAGE_ICON,
                    (dataset_id, icon_key, icon_github, now()),
                )
            else:
                self._exec(conn, Q.DELETE_PACKAGE_ICON, (dataset_id,))
            conn.commit()
        return icon_key, icon_github

    def get_package_icon(self, dataset_id: str) -> tuple[str, str]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_PACKAGE_ICON, (dataset_id,))
            row = cur.fetchone()
        if row is None:
            return "", ""
        return str(row["icon_key"] or ""), str(row["icon_github"] or "")

    def package_icons(self) -> dict[str, tuple[str, str]]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_PACKAGE_ICONS)
            out: dict[str, tuple[str, str]] = {}
            for r in cur.fetchall():
                key = str(r["icon_key"] or "")
                github = str(r["icon_github"] or "")
                if key or github:
                    out[str(r["dataset_id"])] = (key, github)
            return out

    def increment_package_download(self, dataset_id: str) -> None:
        did = (dataset_id or "").strip()
        if not did:
            raise ValueError("dataset_id required")
        with self._connect() as conn:
            self._exec(conn, Q.INCREMENT_PACKAGE_DOWNLOAD, (did,))
            conn.commit()

    def package_download_counts(self, dataset_ids: list[str] | set[str]) -> dict[str, int]:
        ids = sorted({d for d in dataset_ids if d})
        if not ids:
            return {}
        with self._connect() as conn:
            cur = self._exec(conn, Q.select_package_download_counts_query(len(ids)), ids)
            return {str(r["dataset_id"]): int(r["download_count"] or 0) for r in cur.fetchall()}

    def add_package_favorite(self, user_id: str, dataset_id: str) -> None:
        uid = _normalize_user_id(user_id) or ""
        did = (dataset_id or "").strip()
        if not uid or not did:
            raise ValueError("user_id and dataset_id required")
        with self._connect() as conn:
            self._exec(conn, Q.INSERT_PACKAGE_FAVORITE, (uid, did, now()))
            conn.commit()

    def remove_package_favorite(self, user_id: str, dataset_id: str) -> None:
        uid = _normalize_user_id(user_id) or ""
        did = (dataset_id or "").strip()
        if not uid or not did:
            raise ValueError("user_id and dataset_id required")
        with self._connect() as conn:
            self._exec(conn, Q.DELETE_PACKAGE_FAVORITE, (uid, did))
            conn.commit()

    def package_favorite_counts(self, dataset_ids: list[str] | set[str]) -> dict[str, int]:
        ids = sorted({d for d in dataset_ids if d})
        if not ids:
            return {}
        with self._connect() as conn:
            cur = self._exec(conn, Q.select_package_favorite_counts_query(len(ids)), ids)
            return {str(r["dataset_id"]): int(r["favorite_count"] or 0) for r in cur.fetchall()}

    def package_favorites_for_user(
        self, user_id: str, dataset_ids: list[str] | set[str]
    ) -> set[str]:
        uid = _normalize_user_id(user_id) or ""
        ids = sorted({d for d in dataset_ids if d})
        if not uid or not ids:
            return set()
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.select_package_favorites_for_user_query(len(ids)),
                [uid, *ids],
            )
            return {str(r["dataset_id"]) for r in cur.fetchall()}
