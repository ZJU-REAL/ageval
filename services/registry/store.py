"""Registry metadata, tokens, results, and blob storage.

Unit tests: SQLite + Memory blob.
Compose / production: Postgres + S3-compatible (RustFS).

Raw API tokens are never persisted — only sha256 digests.
Visibility is only ``public`` | ``private``.
Packages require ``org_id`` on new publishes; results carry ``uploaded_by``
and optional share targets (org / user). Private read is ownership/membership
based (admin bypass); scopes alone no longer grant global private sight.

Blob and token adapters live in ``blobs.py`` / ``tokens.py`` and are
re-exported here while importers migrate.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.registry import queries as Q
from services.registry.blobs import (  # noqa: F401
    FilesystemBlobStore,
    MemoryBlobStore,
    S3BlobStore,
)
from services.registry.protocols import MetadataStoreProtocol
from services.registry.tokens import (  # noqa: F401
    ADMIN_SCOPES,
    DEFAULT_LOGIN_SCOPES,
    PersistentTokenStore,
    PostgresTokenStore,
    SqliteTokenStore,
    TokenInfo,
    TokenStore,
    _normalize_user_id,
)

# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReleaseRow:
    dataset_id: str
    version: str
    visibility: str
    package_digest: str
    blob_digest: str
    size: int
    media_type: str
    created_at: float
    org_id: str | None = None
    uploaded_by: str = ""


@dataclass(frozen=True, slots=True)
class AttemptResultRow:
    """Sealed Attempt evidence bundle metadata (not a Dataset package)."""

    run_id: str
    dataset_id: str
    task_id: str
    lock_digest: str
    status: str
    visibility: str
    blob_digest: str
    size: int
    created_at: float
    dataset_version: str = ""
    uploaded_by: str = ""
    # Optional link to parent suite/job (#43); empty on standalone uploads.
    suite_run_id: str = ""
    environment: str = ""
    agent_label: str = ""
    model_label: str = ""
    score: float | None = None


@dataclass(frozen=True, slots=True)
class SuiteResultRow:
    """Suite/job result row: aggregates + per-task refs (not suite PASS).

    Observational leaderboard input for Hub SPA (#22 S5). PASS remains
    per-task evaluator only.
    """

    suite_run_id: str
    dataset_id: str
    dataset_version: str
    visibility: str
    pass_rate: float
    mean_score: float
    metrics_json: str
    tasks_json: str
    agent_label: str
    model_label: str
    blob_digest: str
    size: int
    exit_code: int
    created_at: float
    # #42 config comparability (optional; empty/default on legacy rows)
    config_json: str = "{}"
    uploaded_by: str = ""
    complete: bool = False
    bound_kind: str = "unknown"
    task_set_digest: str = ""
    board_listed: bool = False


@dataclass(frozen=True, slots=True)
class ResourceRequestRow:
    request_id: str
    kind: str
    status: str
    suite_run_id: str
    dataset_id: str
    applicant: str
    owner_org_id: str
    agent_ref: str
    created_at: float
    decided_at: float | None = None
    decided_by: str = ""
    canonical_model: str = ""


@dataclass(frozen=True, slots=True)
class DraftRow:
    """One current draft slot per dataset (not a release)."""

    dataset_id: str
    org_id: str
    visibility: str
    package_digest: str
    blob_digest: str
    size: int
    media_type: str
    package_kind: str
    uploaded_by: str
    updated_at: float

    def as_release(self) -> ReleaseRow:
        return ReleaseRow(
            dataset_id=self.dataset_id,
            version="draft",
            visibility=self.visibility,
            package_digest=self.package_digest,
            blob_digest=self.blob_digest,
            size=self.size,
            media_type=self.media_type,
            created_at=self.updated_at,
            org_id=self.org_id,
            uploaded_by=self.uploaded_by,
        )


@dataclass(frozen=True, slots=True)
class DatasetAclRow:
    dataset_id: str
    user_id: str
    role: str
    created_at: float


@dataclass(frozen=True, slots=True)
class OrgRow:
    org_id: str
    name: str
    display_name: str
    description: str
    is_claimable: bool
    created_at: float
    icon_key: str = ""
    icon_github: str = ""


@dataclass(frozen=True, slots=True)
class MembershipRow:
    org_id: str
    user_id: str
    role: str
    created_at: float


@dataclass(frozen=True, slots=True)
class UserProfileRow:
    """GitHub profile snapshot written at Registry login (not a credential)."""

    user_id: str
    display_name: str
    avatar_url: str
    github_id: str
    description: str
    updated_at: float


@dataclass(frozen=True, slots=True)
class ResultShareRow:
    result_kind: str  # attempt | suite
    result_id: str
    target_type: str  # org | user
    target_id: str
    created_at: float


@dataclass(frozen=True, slots=True)
class OrgInviteKeyRow:
    """Org invite key — at rest: token_hash + token_prefix only (no plaintext).

    Full secret is generated by the HTTP layer and returned **once** on create;
    redeem looks up by SHA-256 hash. Owner list/revoke never re-materialize the
    secret (industry default for invite/API keys).
    """

    key_id: str
    org_id: str
    token_hash: str
    token_prefix: str
    created_by: str
    max_uses: int | None
    use_count: int
    expires_at: float | None
    revoked_at: float | None
    created_at: float


# ---------------------------------------------------------------------------
# Metadata (packages + attempt results + orgs + shares)
# ---------------------------------------------------------------------------


class MetadataStore(MetadataStoreProtocol):
    """One metadata repository; SQLite / Postgres only differ in the adapter."""

    def __init__(self, db_path: Path | None = None, *, adapter: Any | None = None) -> None:
        from services.registry.sql_adapter import SqliteAdapter

        if adapter is not None:
            self._adapter = adapter
        else:
            if db_path is None:
                raise TypeError("MetadataStore requires db_path or adapter")
            self._adapter = SqliteAdapter(db_path)
        self.db_path = getattr(self._adapter, "db_path", db_path)
        self._init()

    def _connect(self) -> Any:
        return self._adapter.connect()

    def _exec(self, conn: Any, sql: str, params: Any = ()) -> Any:
        return self._adapter.execute(conn, sql, params)

    def _init(self) -> None:
        with self._connect() as conn:
            self._adapter.lock_schema(conn)
            for stmt in Q.SCHEMA_STATEMENTS:
                if "api_tokens" in stmt:
                    continue
                self._exec(conn, stmt)
            for table, column, decl in Q.SCHEMA_MIGRATIONS:
                self._adapter.add_column(conn, table, column, decl)
            for table, column in Q.SCHEMA_INTEGER_FLAGS:
                self._adapter.align_integer_flag(conn, table, column)
            conn.commit()

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

    def insert_attempt(self, row: AttemptResultRow) -> None:
        with self._connect() as conn:
            try:
                self._exec(
                    conn,
                    Q.INSERT_ATTEMPT,
                    (
                        row.run_id,
                        row.dataset_id,
                        row.dataset_version,
                        row.task_id,
                        row.lock_digest,
                        row.status,
                        row.visibility,
                        row.blob_digest,
                        row.size,
                        row.created_at,
                        row.uploaded_by or "",
                        row.suite_run_id or "",
                        row.environment or "",
                        row.agent_label or "",
                        row.model_label or "",
                        row.score,
                    ),
                )
                conn.commit()
            except self._adapter.integrity_error as exc:
                raise ValueError("attempt result already exists") from exc

    def get_attempt(self, run_id: str) -> AttemptResultRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_ATTEMPT, (run_id,))
            r = cur.fetchone()
            return self._attempt_row(r) if r else None

    def attempts_for_ids(self, run_ids: list[str] | set[str]) -> list[AttemptResultRow]:
        """Return attempt rows for the given run_ids (any visibility; caller filters)."""
        ids = sorted({str(r).strip() for r in run_ids if r and str(r).strip()})
        if not ids:
            return []
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.select_attempts_in_query(len(ids)),
                ids,
            )
            return [self._attempt_row(r) for r in cur.fetchall()]

    def existing_attempt_ids(self, run_ids: list[str] | set[str]) -> set[str]:
        """Return the subset of *run_ids* that already have attempt rows (any visibility)."""
        return {row.run_id for row in self.attempts_for_ids(run_ids)}

    def list_attempts(
        self,
        *,
        dataset_id: str | None = None,
        task_id: str | None = None,
        standalone: bool = False,
        include_private: bool = False,
    ) -> list[AttemptResultRow]:
        sql, params = Q.list_attempts_query(
            dataset_id=dataset_id,
            task_id=task_id,
            standalone=standalone,
            include_private=include_private,
        )
        with self._connect() as conn:
            cur = self._exec(conn, sql, params)
            return [self._attempt_row(r) for r in cur.fetchall()]

    def insert_suite(self, row: SuiteResultRow) -> None:
        with self._connect() as conn:
            try:
                self._exec(
                    conn,
                    Q.INSERT_SUITE,
                    (
                        row.suite_run_id,
                        row.dataset_id,
                        row.dataset_version,
                        row.visibility,
                        row.pass_rate,
                        row.mean_score,
                        row.metrics_json,
                        row.tasks_json,
                        row.agent_label,
                        row.model_label,
                        row.blob_digest,
                        row.size,
                        row.exit_code,
                        row.created_at,
                        row.config_json or "{}",
                        row.uploaded_by or "",
                        1 if row.complete else 0,
                        row.bound_kind or "unknown",
                        row.task_set_digest or "",
                    ),
                )
                conn.commit()
            except self._adapter.integrity_error as exc:
                raise ValueError("suite result already exists") from exc

    def get_suite(self, suite_run_id: str) -> SuiteResultRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_SUITE, (suite_run_id,))
            r = cur.fetchone()
            return self._suite_row(r) if r else None

    def list_suites(
        self,
        *,
        dataset_id: str | None = None,
        include_private: bool = False,
    ) -> list[SuiteResultRow]:
        sql, params = Q.list_suites_query(dataset_id=dataset_id, include_private=include_private)
        with self._connect() as conn:
            cur = self._exec(conn, sql, params)
            return [self._suite_row(r) for r in cur.fetchall()]

    def delete_attempt(self, run_id: str) -> AttemptResultRow:
        """Delete attempt row and its shares. Raises LookupError if missing."""
        row = self.get_attempt(run_id)
        if row is None:
            raise LookupError("attempt not found")
        with self._connect() as conn:
            self._exec(conn, Q.DELETE_ATTEMPT_SHARES, (run_id,))
            self._exec(conn, Q.DELETE_ATTEMPT, (run_id,))
            conn.commit()
        return row

    def set_attempt_visibility(self, run_id: str, visibility: str) -> AttemptResultRow:
        if visibility not in {"public", "private"}:
            raise ValueError("bad visibility")
        row = self.get_attempt(run_id)
        if row is None:
            raise LookupError("attempt not found")
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPDATE_ATTEMPT_VISIBILITY,
                (visibility, run_id),
            )
            conn.commit()
        updated = self.get_attempt(run_id)
        assert updated is not None
        return updated

    def delete_suite(self, suite_run_id: str) -> SuiteResultRow:
        """Delete suite row, shares, consents, and requests (does not cascade attempts)."""
        row = self.get_suite(suite_run_id)
        if row is None:
            raise LookupError("suite not found")
        with self._connect() as conn:
            self._exec(conn, Q.DELETE_SUITE_SHARES, (suite_run_id,))
            self._exec(conn, Q.DELETE_SUITE_CONSENTS, (suite_run_id,))
            self._exec(conn, Q.DELETE_SUITE_REQUESTS, (suite_run_id,))
            self._exec(conn, Q.DELETE_SUITE, (suite_run_id,))
            conn.commit()
        return row

    def update_suite_slot(
        self,
        suite_run_id: str,
        *,
        pass_rate: float,
        mean_score: float,
        metrics_json: str,
        tasks_json: str,
        exit_code: int,
        complete: bool,
    ) -> SuiteResultRow:
        """In-place slot append. Keeps created_at, owner, visibility, shares, blob."""
        row = self.get_suite(suite_run_id)
        if row is None:
            raise LookupError("suite not found")
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPDATE_SUITE_SLOT,
                (
                    pass_rate,
                    mean_score,
                    metrics_json,
                    tasks_json,
                    exit_code,
                    1 if complete else 0,
                    suite_run_id,
                ),
            )
            conn.commit()
        updated = self.get_suite(suite_run_id)
        assert updated is not None
        return updated

    def update_suite_config_json(self, suite_run_id: str, config_json: str) -> SuiteResultRow:
        """Patch stored suite config_json (overlay provenance). Lock bytes stay put."""
        row = self.get_suite(suite_run_id)
        if row is None:
            raise LookupError("suite not found")
        with self._connect() as conn:
            self._exec(conn, Q.UPDATE_SUITE_CONFIG_JSON, (config_json, suite_run_id))
            conn.commit()
        updated = self.get_suite(suite_run_id)
        assert updated is not None
        return updated

    def grant_agent_consent(
        self,
        *,
        suite_run_id: str,
        package_id: str,
        granted_by: str,
        source: str,
    ) -> None:
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPSERT_SUITE_AGENT_CONSENT,
                (suite_run_id, package_id, granted_by, source, now()),
            )
            conn.commit()

    def set_suite_canonical_model(
        self, suite_run_id: str, overlay_model: str, canonical_model: str
    ) -> None:
        overlay = overlay_model.strip()
        canonical = canonical_model.strip()
        if not overlay or not canonical:
            return
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPSERT_SUITE_CANONICAL_MODEL,
                (suite_run_id, overlay, canonical),
            )
            conn.commit()

    def list_canonical_models_for_suites(
        self, suite_run_ids: list[str]
    ) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {sid: {} for sid in suite_run_ids}
        ids = [sid for sid in suite_run_ids if sid]
        if not ids:
            return out
        placeholders = ",".join("?" * len(ids))
        sql = Q.LIST_CANONICAL_MODELS_FOR_SUITES.format(placeholders=placeholders)
        with self._connect() as conn:
            cur = self._exec(conn, sql, tuple(ids))
            for row in cur.fetchall():
                sid = str(row["suite_run_id"] or "")
                overlay = str(row["overlay_model"] or "").strip()
                canonical = str(row["canonical_model"] or "").strip()
                if sid and overlay and canonical:
                    out.setdefault(sid, {})[overlay] = canonical
        return out

    def has_agent_consent(self, suite_run_id: str, package_id: str) -> bool:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_SUITE_AGENT_CONSENT, (suite_run_id, package_id))
            return cur.fetchone() is not None

    def list_agent_consents(self, suite_run_id: str) -> list[str]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.LIST_SUITE_AGENT_CONSENTS, (suite_run_id,))
            return [str(r["package_id"]) for r in cur.fetchall()]

    def set_suite_board_listed(self, suite_run_id: str, listed: bool) -> SuiteResultRow:
        row = self.get_suite(suite_run_id)
        if row is None:
            raise LookupError("suite not found")
        with self._connect() as conn:
            self._exec(conn, Q.UPDATE_SUITE_BOARD_LISTED, (1 if listed else 0, suite_run_id))
            conn.commit()
        updated = self.get_suite(suite_run_id)
        assert updated is not None
        return updated

    def insert_resource_request(self, row: ResourceRequestRow) -> None:
        with self._connect() as conn:
            try:
                self._exec(
                    conn,
                    Q.INSERT_RESOURCE_REQUEST,
                    (
                        row.request_id,
                        row.kind,
                        row.status,
                        row.suite_run_id,
                        row.dataset_id,
                        row.applicant,
                        row.owner_org_id,
                        row.agent_ref,
                        row.canonical_model,
                        row.created_at,
                        row.decided_at,
                        row.decided_by,
                    ),
                )
                conn.commit()
            except self._adapter.integrity_error as exc:
                raise ValueError("request already exists") from exc

    def get_resource_request(self, request_id: str) -> ResourceRequestRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_RESOURCE_REQUEST, (request_id,))
            r = cur.fetchone()
            return self._request_row(r) if r else None

    def get_pending_request(
        self, *, kind: str, suite_run_id: str, agent_ref: str = ""
    ) -> ResourceRequestRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_PENDING_REQUEST, (kind, suite_run_id, agent_ref))
            r = cur.fetchone()
            return self._request_row(r) if r else None

    def list_resource_requests_by_ids(self, request_ids: list[str]) -> list[ResourceRequestRow]:
        ids = [i for i in request_ids if i]
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        sql = Q.LIST_RESOURCE_REQUESTS_BY_IDS.format(placeholders=placeholders)
        with self._connect() as conn:
            cur = self._exec(conn, sql, tuple(ids))
            return [self._request_row(r) for r in cur.fetchall()]

    def list_inbox_requests(
        self, *, org_ids: list[str], status: str | None = "pending"
    ) -> list[ResourceRequestRow]:
        ids = [o for o in org_ids if o]
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        sql = Q.LIST_INBOX_REQUESTS.format(placeholders=placeholders)
        params: tuple[Any, ...]
        if status:
            sql += " AND status=?"
            params = (*ids, status)
        else:
            params = tuple(ids)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            cur = self._exec(conn, sql, params)
            return [self._request_row(r) for r in cur.fetchall()]

    def list_suite_requests(self, suite_run_id: str) -> list[ResourceRequestRow]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.LIST_SUITE_REQUESTS, (suite_run_id,))
            return [self._request_row(r) for r in cur.fetchall()]

    def update_resource_request_status(
        self, request_id: str, *, status: str, decided_by: str
    ) -> ResourceRequestRow:
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPDATE_RESOURCE_REQUEST_STATUS,
                (status, now(), decided_by, request_id),
            )
            conn.commit()
        row = self.get_resource_request(request_id)
        if row is None:
            raise LookupError("request not found")
        return row

    @staticmethod
    def _request_row(r: sqlite3.Row) -> ResourceRequestRow:
        keys = r.keys()
        decided_at: float | None = None
        if "decided_at" in keys and r["decided_at"] is not None:
            try:
                decided_at = float(r["decided_at"])
            except (TypeError, ValueError):
                decided_at = None
        return ResourceRequestRow(
            request_id=str(r["request_id"]),
            kind=str(r["kind"]),
            status=str(r["status"]),
            suite_run_id=str(r["suite_run_id"]),
            dataset_id=str(r["dataset_id"]),
            applicant=str(r["applicant"]),
            owner_org_id=str(r["owner_org_id"]),
            agent_ref=str(r["agent_ref"] or ""),
            created_at=float(r["created_at"]),
            decided_at=decided_at,
            decided_by=str(r["decided_by"] or "") if "decided_by" in keys else "",
            canonical_model=(str(r["canonical_model"] or "") if "canonical_model" in keys else ""),
        )

    def list_agent_consents_for_suites(self, suite_run_ids: list[str]) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {sid: set() for sid in suite_run_ids}
        ids = [sid for sid in suite_run_ids if sid]
        if not ids:
            return out
        placeholders = ",".join("?" * len(ids))
        sql = Q.LIST_AGENT_CONSENTS_FOR_SUITES.format(placeholders=placeholders)
        with self._connect() as conn:
            cur = self._exec(conn, sql, tuple(ids))
            for r in cur.fetchall():
                sid = str(r["suite_run_id"])
                out.setdefault(sid, set()).add(str(r["package_id"]))
        return out

    def get_performance_collect_mode(self, package_id: str) -> str | None:
        pid = (package_id or "").strip()
        if not pid:
            return None
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_PERFORMANCE_COLLECT, (pid,))
            row = cur.fetchone()
        if row is None:
            return None
        return str(row["mode"] or "").strip() or None

    def set_performance_collect_mode(self, *, package_id: str, mode: str, updated_by: str) -> None:
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPSERT_PERFORMANCE_COLLECT,
                (package_id, mode, updated_by, now()),
            )
            conn.commit()

    def list_hidden_inbox_ids(self, user_id: str) -> set[str]:
        uid = _normalize_user_id(user_id) or ""
        if not uid:
            return set()
        with self._connect() as conn:
            cur = self._exec(conn, Q.LIST_INBOX_HIDDEN_FOR_USER, (uid,))
            return {str(r["request_id"]) for r in cur.fetchall()}

    def hide_inbox_requests(self, *, user_id: str, request_ids: list[str]) -> None:
        uid = _normalize_user_id(user_id) or ""
        ids = [i for i in request_ids if i]
        if not uid or not ids:
            return
        stamp = now()
        with self._connect() as conn:
            for rid in ids:
                self._exec(conn, Q.UPSERT_INBOX_HIDDEN, (uid, rid, stamp))
            conn.commit()

    def revoke_agent_consent(self, *, suite_run_id: str, package_id: str) -> None:
        with self._connect() as conn:
            self._exec(conn, Q.DELETE_SUITE_PACKAGE_CONSENT, (suite_run_id, package_id))
            conn.commit()

    def set_suite_visibility(self, suite_run_id: str, visibility: str) -> SuiteResultRow:
        if visibility not in {"public", "private"}:
            raise ValueError("bad visibility")
        row = self.get_suite(suite_run_id)
        if row is None:
            raise LookupError("suite not found")
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPDATE_SUITE_VISIBILITY,
                (visibility, suite_run_id),
            )
            conn.commit()
        updated = self.get_suite(suite_run_id)
        assert updated is not None
        return updated

    def list_attempts_for_suite(self, suite_run_id: str) -> list[AttemptResultRow]:
        """Attempts whose suite_run_id column matches (any visibility)."""
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_ATTEMPTS_FOR_SUITE,
                (suite_run_id,),
            )
            return [self._attempt_row(r) for r in cur.fetchall()]

    def count_attempt_blob_refs(self, blob_digest: str) -> int:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.COUNT_ATTEMPT_BLOB_REFS,
                (blob_digest,),
            )
            return int(cur.fetchone()["n"])

    def count_suite_blob_refs(self, blob_digest: str) -> int:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.COUNT_SUITE_BLOB_REFS,
                (blob_digest,),
            )
            return int(cur.fetchone()["n"])

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

    @staticmethod
    def _attempt_row(r: sqlite3.Row) -> AttemptResultRow:
        keys = r.keys()
        uploaded_by = str(r["uploaded_by"]) if "uploaded_by" in keys and r["uploaded_by"] else ""
        suite_run_id = (
            str(r["suite_run_id"]) if "suite_run_id" in keys and r["suite_run_id"] else ""
        )
        environment = str(r["environment"]) if "environment" in keys and r["environment"] else ""
        agent_label = str(r["agent_label"]) if "agent_label" in keys and r["agent_label"] else ""
        model_label = str(r["model_label"]) if "model_label" in keys and r["model_label"] else ""
        score: float | None = None
        if "score" in keys and r["score"] is not None:
            try:
                score = float(r["score"])
            except (TypeError, ValueError):
                score = None
        return AttemptResultRow(
            run_id=r["run_id"],
            dataset_id=r["dataset_id"],
            dataset_version=str(r["dataset_version"])
            if "dataset_version" in keys and r["dataset_version"]
            else "",
            task_id=r["task_id"],
            lock_digest=r["lock_digest"],
            status=r["status"],
            visibility=r["visibility"],
            blob_digest=r["blob_digest"],
            size=int(r["size"]),
            created_at=float(r["created_at"]),
            uploaded_by=uploaded_by,
            suite_run_id=suite_run_id,
            environment=environment,
            agent_label=agent_label,
            model_label=model_label,
            score=score,
        )

    @staticmethod
    def _suite_row(r: sqlite3.Row) -> SuiteResultRow:
        keys = r.keys()
        config_json = str(r["config_json"]) if "config_json" in keys and r["config_json"] else "{}"
        uploaded_by = str(r["uploaded_by"]) if "uploaded_by" in keys and r["uploaded_by"] else ""
        complete = False
        if "complete" in keys and r["complete"] is not None:
            complete = bool(int(r["complete"]))
        bound_kind = str(r["bound_kind"]) if "bound_kind" in keys and r["bound_kind"] else "unknown"
        task_set_digest = (
            str(r["task_set_digest"]) if "task_set_digest" in keys and r["task_set_digest"] else ""
        )
        board_listed = False
        if "board_listed" in keys and r["board_listed"] is not None:
            board_listed = bool(int(r["board_listed"]))
        return SuiteResultRow(
            suite_run_id=r["suite_run_id"],
            dataset_id=r["dataset_id"],
            dataset_version=r["dataset_version"],
            visibility=r["visibility"],
            pass_rate=float(r["pass_rate"]),
            mean_score=float(r["mean_score"]),
            metrics_json=str(r["metrics_json"]),
            tasks_json=str(r["tasks_json"]),
            agent_label=str(r["agent_label"] or ""),
            model_label=str(r["model_label"] or ""),
            blob_digest=r["blob_digest"],
            size=int(r["size"]),
            exit_code=int(r["exit_code"]),
            created_at=float(r["created_at"]),
            config_json=config_json,
            uploaded_by=uploaded_by,
            complete=complete,
            bound_kind=bound_kind,
            task_set_digest=task_set_digest,
            board_listed=board_listed,
        )

    # ---- organizations ---------------------------------------------------

    def create_org(
        self,
        *,
        name: str,
        owner_user_id: str,
        display_name: str = "",
        description: str = "",
        is_claimable: bool = False,
    ) -> OrgRow:
        org_id = name
        row = OrgRow(
            org_id=org_id,
            name=name,
            display_name=display_name or name,
            description=description,
            is_claimable=is_claimable,
            created_at=now(),
        )
        with self._connect() as conn:
            try:
                self._exec(
                    conn,
                    Q.INSERT_ORG,
                    (
                        row.org_id,
                        row.name,
                        row.display_name,
                        row.description,
                        1 if row.is_claimable else 0,
                        row.created_at,
                    ),
                )
                self._exec(
                    conn,
                    Q.INSERT_ORG_OWNER_MEMBERSHIP,
                    (row.org_id, owner_user_id, row.created_at),
                )
                conn.commit()
            except self._adapter.integrity_error as exc:
                raise ValueError("org already exists") from exc
        return row

    def update_org_display_name(self, org_id: str, display_name: str) -> OrgRow:
        return self.update_org(org_id, display_name=display_name)

    def update_org(
        self,
        org_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        icon_key: str | None = None,
        icon_github: str | None = None,
    ) -> OrgRow:
        has_name = display_name is not None
        has_desc = description is not None
        has_icons = icon_key is not None or icon_github is not None
        if not (has_name or has_desc or has_icons):
            raise ValueError("nothing to update")
        params: list[str] = []
        if has_name:
            params.append(display_name or "")
        if has_desc:
            params.append(description or "")
        if has_icons:
            params.append(icon_key or "")
            params.append(icon_github or "")
        params.append(org_id)
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.update_org_query(display_name=has_name, description=has_desc, icons=has_icons),
                tuple(params),
            )
            if getattr(cur, "rowcount", 1) == 0:
                raise LookupError("org not found")
            conn.commit()
        org = self.get_org(org_id)
        if org is None:
            raise LookupError("org not found")
        return org

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

    def get_org(self, org_id: str) -> OrgRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_ORG, (org_id,))
            r = cur.fetchone()
            return self._org_row(r) if r else None

    def list_orgs_for_user(self, user_id: str) -> list[tuple[OrgRow, str]]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_USER_ORGS, (user_id,))
            out: list[tuple[OrgRow, str]] = []
            for r in cur.fetchall():
                out.append((self._org_row(r), str(r["membership_role"])))
            return out

    def claim_org(self, org_id: str, user_id: str) -> OrgRow:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_ORG, (org_id,))
            r = cur.fetchone()
            if r is None:
                raise LookupError("org not found")
            org = self._org_row(r)
            if not org.is_claimable:
                raise PermissionError("org not claimable")
            owners = self._exec(
                conn,
                Q.SELECT_ORG_HAS_OWNER,
                (org_id,),
            ).fetchone()
            if owners is not None:
                raise PermissionError("org already claimed")
            self._exec(
                conn,
                Q.INSERT_ORG_MEMBERSHIP_OWNER,
                (org_id, user_id, now()),
            )
            self._exec(
                conn,
                Q.UPDATE_ORG_CLAIMED,
                (org_id,),
            )
            conn.commit()
        got = self.get_org(org_id)
        assert got is not None
        return got

    def add_member(self, org_id: str, user_id: str, *, role: str = "member") -> MembershipRow:
        if role not in {"owner", "member"}:
            raise ValueError("invalid role")
        ts = now()
        with self._connect() as conn:
            if self.get_org(org_id) is None:
                raise LookupError("org not found")
            try:
                self._exec(
                    conn,
                    Q.INSERT_ORG_MEMBERSHIP,
                    (org_id, user_id, role, ts),
                )
                conn.commit()
            except self._adapter.integrity_error as exc:
                raise ValueError("membership exists") from exc
        return MembershipRow(org_id=org_id, user_id=user_id, role=role, created_at=ts)

    def set_member_role(self, org_id: str, user_id: str, *, role: str) -> MembershipRow:
        if role not in {"owner", "member"}:
            raise ValueError("invalid role")
        uid = _normalize_user_id(user_id) or user_id
        mem = self.membership(org_id, uid)
        if mem is None:
            raise LookupError("membership not found")
        if mem.role == role:
            return mem
        if mem.role == "owner" and role == "member" and self.count_org_owners(org_id) <= 1:
            raise PermissionError("sole owner cannot be demoted; dissolve the organization instead")
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.UPDATE_ORG_MEMBERSHIP_ROLE,
                (role, org_id, uid),
            )
            if cur.rowcount == 0:
                raise LookupError("membership not found")
            conn.commit()
        updated = self.membership(org_id, uid)
        if updated is None:
            raise LookupError("membership not found")
        return updated

    def transfer_owner(
        self, org_id: str, *, from_user_id: str, to_user_id: str
    ) -> tuple[MembershipRow, MembershipRow]:
        """Atomic: target → owner, caller → member. Target must already be a member."""
        src = _normalize_user_id(from_user_id) or from_user_id
        dst = _normalize_user_id(to_user_id) or to_user_id
        if not src or not dst:
            raise ValueError("user_id required")
        if src == dst:
            raise ValueError("cannot transfer to self")
        target = self.membership(org_id, dst)
        if target is None:
            raise LookupError("membership not found")
        caller = self.membership(org_id, src)
        if caller is None:
            raise LookupError("caller membership not found")
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPDATE_ORG_MEMBERSHIP_ROLE,
                ("owner", org_id, dst),
            )
            self._exec(
                conn,
                Q.UPDATE_ORG_MEMBERSHIP_ROLE,
                ("member", org_id, src),
            )
            conn.commit()
        new_target = self.membership(org_id, dst)
        new_caller = self.membership(org_id, src)
        if new_target is None or new_caller is None:
            raise LookupError("membership not found")
        return new_target, new_caller

    def remove_member(self, org_id: str, user_id: str) -> None:
        uid = _normalize_user_id(user_id) or user_id
        mem = self.membership(org_id, uid)
        if mem is None:
            raise LookupError("membership not found")
        if mem.role == "owner" and self.count_org_owners(org_id) <= 1:
            raise PermissionError("sole owner cannot be removed; dissolve the organization instead")
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.DELETE_ORG_MEMBERSHIP,
                (org_id, uid),
            )
            if cur.rowcount == 0:
                raise LookupError("membership not found")
            conn.commit()

    def count_org_owners(self, org_id: str) -> int:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.COUNT_ORG_OWNERS,
                (org_id,),
            )
            r = cur.fetchone()
            return int(r["n"] if r is not None else 0)

    def count_org_packages(self, org_id: str) -> int:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.COUNT_ORG_PACKAGES,
                (org_id,),
            )
            r = cur.fetchone()
            return int(r["n"] if r is not None else 0)

    def leave_org(self, org_id: str, user_id: str) -> None:
        """Member (or non-sole owner) leaves the org."""
        uid = _normalize_user_id(user_id) or user_id
        mem = self.membership(org_id, uid)
        if mem is None:
            raise LookupError("membership not found")
        if mem.role == "owner" and self.count_org_owners(org_id) <= 1:
            raise PermissionError("sole owner cannot leave; dissolve the organization instead")
        self.remove_member(org_id, uid)

    def delete_org(self, org_id: str) -> None:
        """Dissolve org: memberships + invite keys + org row. Fail if packages remain."""
        if self.get_org(org_id) is None:
            raise LookupError("org not found")
        n_pkg = self.count_org_packages(org_id)
        if n_pkg > 0:
            raise ValueError(
                f"org still has {n_pkg} package release(s); unpublish or reassign first"
            )
        with self._connect() as conn:
            self._exec(conn, Q.DELETE_ORG_INVITE_KEYS, (org_id,))
            self._exec(conn, Q.DELETE_ORG_MEMBERSHIPS, (org_id,))
            self._exec(conn, Q.DELETE_ORG_RESULT_SHARES, (org_id,))
            cur = self._exec(conn, Q.DELETE_ORG, (org_id,))
            if cur.rowcount == 0:
                raise LookupError("org not found")
            conn.commit()

    def list_members(self, org_id: str) -> list[MembershipRow]:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_ORG_MEMBERS,
                (org_id,),
            )
            return [
                MembershipRow(
                    org_id=str(r["org_id"]),
                    user_id=str(r["user_id"]),
                    role=str(r["role"]),
                    created_at=float(r["created_at"]),
                )
                for r in cur.fetchall()
            ]

    def membership(self, org_id: str, user_id: str) -> MembershipRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_MEMBERSHIP, (org_id, user_id))
            r = cur.fetchone()
            if r is None:
                return None
            return MembershipRow(
                org_id=str(r["org_id"]),
                user_id=str(r["user_id"]),
                role=str(r["role"]),
                created_at=float(r["created_at"]),
            )

    def create_invite_key(
        self,
        *,
        org_id: str,
        created_by: str,
        token_hash: str,
        token_prefix: str,
        max_uses: int | None = None,
        expires_at: float | None = None,
        key_id: str | None = None,
    ) -> OrgInviteKeyRow:
        import secrets as _secrets

        if self.get_org(org_id) is None:
            raise LookupError("org not found")
        if max_uses is not None and max_uses < 1:
            raise ValueError("max_uses must be >= 1")
        if not token_hash or not token_prefix:
            raise ValueError("token_hash and token_prefix required")
        kid = key_id or _secrets.token_hex(8)
        row = OrgInviteKeyRow(
            key_id=kid,
            org_id=org_id,
            token_hash=token_hash,
            token_prefix=token_prefix,
            created_by=created_by or "",
            max_uses=max_uses,
            use_count=0,
            expires_at=expires_at,
            revoked_at=None,
            created_at=now(),
        )
        with self._connect() as conn:
            self._exec(
                conn,
                Q.INSERT_INVITE_KEY,
                (
                    row.key_id,
                    row.org_id,
                    row.token_hash,
                    row.token_prefix,
                    row.created_by,
                    row.max_uses,
                    row.use_count,
                    row.expires_at,
                    row.revoked_at,
                    row.created_at,
                ),
            )
            conn.commit()
        return row

    def list_invite_keys(self, org_id: str) -> list[OrgInviteKeyRow]:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_INVITE_KEYS,
                (org_id,),
            )
            return [self._invite_key_row(r) for r in cur.fetchall()]

    def get_invite_key(self, org_id: str, key_id: str) -> OrgInviteKeyRow | None:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_INVITE_KEY,
                (org_id, key_id),
            )
            r = cur.fetchone()
            return self._invite_key_row(r) if r else None

    def revoke_invite_key(self, org_id: str, key_id: str) -> OrgInviteKeyRow:
        ts = now()
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_INVITE_KEY,
                (org_id, key_id),
            )
            r = cur.fetchone()
            if r is None:
                raise LookupError("invite key not found")
            row = self._invite_key_row(r)
            if row.revoked_at is not None:
                return row
            self._exec(
                conn,
                Q.UPDATE_INVITE_REVOKED,
                (ts, key_id),
            )
            conn.commit()
        out = self.get_invite_key(org_id, key_id)
        assert out is not None
        return out

    def redeem_invite_key(self, *, token_hash: str, user_id: str) -> tuple[OrgRow, MembershipRow]:
        """Join org via invite key. Fail closed on expired / exhausted / revoked.

        ``max_uses`` is enforced by a conditional ``UPDATE`` so concurrent
        redeems cannot over-admit under multi-writer backends.
        """
        uid = _normalize_user_id(user_id) or user_id
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_INVITE_BY_HASH,
                (token_hash,),
            )
            r = cur.fetchone()
            if r is None:
                raise LookupError("invalid invite key")
            inv = self._invite_key_row(r)
            if inv.revoked_at is not None:
                raise PermissionError("invite key revoked")
            if inv.expires_at is not None and inv.expires_at <= now():
                raise PermissionError("invite key expired")
            org = self.get_org(inv.org_id)
            if org is None:
                raise LookupError("org not found")
            existing = self.membership(inv.org_id, uid)
            if existing is not None:
                # Already a member: do not burn use_count.
                return org, existing
            # Claim a slot atomically (check + increment). rowcount==0 ⇒ exhausted.
            claim = self._exec(
                conn,
                Q.CLAIM_INVITE_USE,
                (inv.key_id,),
            )
            if claim.rowcount == 0:
                raise PermissionError("invite key exhausted")
            ts = now()
            try:
                self._exec(
                    conn,
                    Q.INSERT_ORG_MEMBERSHIP_MEMBER,
                    (inv.org_id, uid, ts),
                )
            except self._adapter.integrity_error as exc:
                # Same-transaction rollback drops the claim on context exit.
                raise ValueError("membership exists") from exc
            conn.commit()
            mem = MembershipRow(org_id=inv.org_id, user_id=uid, role="member", created_at=ts)
            return org, mem

    @staticmethod
    def _invite_key_row(r: sqlite3.Row) -> OrgInviteKeyRow:
        max_uses = r["max_uses"]
        expires_at = r["expires_at"]
        revoked_at = r["revoked_at"]
        return OrgInviteKeyRow(
            key_id=str(r["key_id"]),
            org_id=str(r["org_id"]),
            token_hash=str(r["token_hash"]),
            token_prefix=str(r["token_prefix"] or ""),
            created_by=str(r["created_by"] or ""),
            max_uses=int(max_uses) if max_uses is not None else None,
            use_count=int(r["use_count"] or 0),
            expires_at=float(expires_at) if expires_at is not None else None,
            revoked_at=float(revoked_at) if revoked_at is not None else None,
            created_at=float(r["created_at"]),
        )

    def user_org_ids(self, user_id: str) -> set[str]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_USER_ORG_IDS, (user_id,))
            return {str(r["org_id"]) for r in cur.fetchall()}

    # ---- result shares ---------------------------------------------------

    def add_result_share(
        self,
        *,
        result_kind: str,
        result_id: str,
        target_type: str,
        target_id: str,
    ) -> ResultShareRow:
        if result_kind not in {"attempt", "suite"}:
            raise ValueError("invalid result_kind")
        if target_type not in {"org", "user"}:
            raise ValueError("invalid target_type")
        ts = now()
        with self._connect() as conn:
            try:
                self._exec(
                    conn,
                    Q.INSERT_RESULT_SHARE,
                    (result_kind, result_id, target_type, target_id, ts),
                )
                conn.commit()
            except self._adapter.integrity_error as exc:
                raise ValueError("share already exists") from exc
        return ResultShareRow(
            result_kind=result_kind,
            result_id=result_id,
            target_type=target_type,
            target_id=target_id,
            created_at=ts,
        )

    def remove_result_share(
        self,
        *,
        result_kind: str,
        result_id: str,
        target_type: str,
        target_id: str,
    ) -> None:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.DELETE_RESULT_SHARE,
                (result_kind, result_id, target_type, target_id),
            )
            if cur.rowcount == 0:
                raise LookupError("share not found")
            conn.commit()

    def list_result_shares(self, *, result_kind: str, result_id: str) -> list[ResultShareRow]:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_RESULT_SHARES,
                (result_kind, result_id),
            )
            return [
                ResultShareRow(
                    result_kind=str(r["result_kind"]),
                    result_id=str(r["result_id"]),
                    target_type=str(r["target_type"]),
                    target_id=str(r["target_id"]),
                    created_at=float(r["created_at"]),
                )
                for r in cur.fetchall()
            ]

    def result_shared_with_user(
        self,
        *,
        result_kind: str,
        result_id: str,
        user_id: str,
        user_orgs: set[str],
    ) -> bool:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_RESULT_SHARED_USER,
                (result_kind, result_id, user_id),
            )
            if cur.fetchone() is not None:
                return True
            if not user_orgs:
                return False
            orgs = sorted(user_orgs)
            cur = self._exec(
                conn,
                Q.select_result_shared_orgs_query(len(orgs)),
                (result_kind, result_id, *orgs),
            )
            return cur.fetchone() is not None

    @staticmethod
    def _org_row(r: sqlite3.Row) -> OrgRow:
        keys = r.keys()
        return OrgRow(
            org_id=str(r["org_id"]),
            name=str(r["name"]),
            display_name=str(r["display_name"] or ""),
            description=str(r["description"] or ""),
            is_claimable=bool(int(r["is_claimable"])),
            created_at=float(r["created_at"]),
            icon_key=str(r["icon_key"]) if "icon_key" in keys else "",
            icon_github=str(r["icon_github"]) if "icon_github" in keys else "",
        )

    def upsert_user_profile(
        self,
        *,
        user_id: str,
        display_name: str = "",
        avatar_url: str = "",
        github_id: str = "",
    ) -> UserProfileRow:
        uid = _normalize_user_id(user_id) or user_id
        row = UserProfileRow(
            user_id=uid,
            display_name=(display_name or "").strip(),
            avatar_url=(avatar_url or "").strip(),
            github_id=str(github_id or "").strip(),
            description="",
            updated_at=now(),
        )
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPSERT_USER_PROFILE,
                (
                    row.user_id,
                    row.display_name,
                    row.avatar_url,
                    row.github_id,
                    row.updated_at,
                ),
            )
            conn.commit()
        stored = self.get_user_profile(uid)
        if stored is None:
            raise LookupError("user not found")
        return stored

    def get_user_profile(self, user_id: str) -> UserProfileRow | None:
        uid = _normalize_user_id(user_id) or user_id
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_USER_PROFILE,
                (uid,),
            )
            r = cur.fetchone()
            if r is None:
                return None
            return UserProfileRow(
                user_id=str(r["user_id"]),
                display_name=str(r["display_name"] or ""),
                avatar_url=str(r["avatar_url"] or ""),
                github_id=str(r["github_id"] or ""),
                description=str(r["description"] or ""),
                updated_at=float(r["updated_at"]),
            )

    def set_user_description(self, user_id: str, description: str) -> UserProfileRow:
        uid = _normalize_user_id(user_id) or user_id
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPSERT_USER_DESCRIPTION,
                (uid, description, now()),
            )
            conn.commit()
        row = self.get_user_profile(uid)
        if row is None:
            raise LookupError("user not found")
        return row

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

    def get_user_profiles(self, user_ids: list[str] | set[str]) -> dict[str, UserProfileRow]:
        ids = sorted({_normalize_user_id(u) or u for u in user_ids if u})
        if not ids:
            return {}
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.select_user_profiles_in_query(len(ids)),
                ids,
            )
            out: dict[str, UserProfileRow] = {}
            for r in cur.fetchall():
                p = UserProfileRow(
                    user_id=str(r["user_id"]),
                    display_name=str(r["display_name"] or ""),
                    avatar_url=str(r["avatar_url"] or ""),
                    github_id=str(r["github_id"] or ""),
                    description=str(r["description"] or ""),
                    updated_at=float(r["updated_at"]),
                )
                out[p.user_id] = p
            return out


class PostgresMetadataStore(MetadataStore):
    """Postgres metadata: same repository, thin dialect adapter."""

    def __init__(self, database_url: str) -> None:
        from services.registry.sql_adapter import PostgresAdapter

        MetadataStore.__init__(self, adapter=PostgresAdapter(database_url))
        self.database_url = database_url


def package_kind_for_media_type(media_type: str) -> str:
    """Derive list/meta ``package_kind`` from the current vnd.ageval types only."""
    from ageval.registry.media_types import (
        AGENT_MEDIA_TYPE,
        DATASET_MEDIA_TYPE,
        PLUGIN_MEDIA_TYPE,
    )

    if media_type == PLUGIN_MEDIA_TYPE:
        return "plugin"
    if media_type == AGENT_MEDIA_TYPE:
        return "agent"
    if media_type == DATASET_MEDIA_TYPE:
        return "dataset"
    raise ValueError(f"unknown package media_type: {media_type!r}")


def release_to_dict(row: ReleaseRow) -> dict[str, Any]:
    out: dict[str, Any] = {
        "dataset_id": row.dataset_id,
        "version": row.version,
        "visibility": row.visibility,
        "package_digest": row.package_digest,
        "blob_digest": row.blob_digest,
        "size": row.size,
        "media_type": row.media_type,
        "created_at": row.created_at,
    }
    with contextlib.suppress(ValueError):
        out["package_kind"] = package_kind_for_media_type(row.media_type)
    if row.org_id:
        out["org_id"] = row.org_id
    from services.registry.official import is_official_upload_org

    out["official"] = is_official_upload_org(row.org_id)
    if row.uploaded_by:
        out["uploaded_by"] = row.uploaded_by
    if row.version == "draft":
        out["slot"] = "draft"
        out["is_draft"] = True
    return out


def attempt_to_dict(row: AttemptResultRow) -> dict[str, Any]:
    out: dict[str, Any] = {
        "run_id": row.run_id,
        "dataset_id": row.dataset_id,
        "dataset_version": row.dataset_version,
        "task_id": row.task_id,
        "lock_digest": row.lock_digest,
        "status": row.status,
        "visibility": row.visibility,
        "blob_digest": row.blob_digest,
        "size": row.size,
        "created_at": row.created_at,
    }
    if row.uploaded_by:
        out["uploaded_by"] = row.uploaded_by
    if row.suite_run_id:
        out["suite_run_id"] = row.suite_run_id
    if row.environment:
        out["environment"] = row.environment
    if row.agent_label:
        out["agent_label"] = row.agent_label
    if row.model_label:
        out["model_label"] = row.model_label
    if row.score is not None:
        out["score"] = row.score
    return out


def org_to_dict(row: OrgRow) -> dict[str, Any]:
    from services.registry.official import is_official_upload_org

    out: dict[str, Any] = {
        "org_id": row.org_id,
        "name": row.name,
        "display_name": row.display_name,
        "description": row.description,
        "is_claimable": row.is_claimable,
        "created_at": row.created_at,
        "official": is_official_upload_org(row.org_id),
    }
    if row.icon_key:
        out["icon_key"] = row.icon_key
    if row.icon_github:
        out["icon_github"] = row.icon_github
    return out


def membership_to_dict(
    row: MembershipRow,
    *,
    profile: UserProfileRow | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "org_id": row.org_id,
        "user_id": row.user_id,
        "role": row.role,
        "created_at": row.created_at,
    }
    if profile is not None:
        if profile.display_name:
            out["display_name"] = profile.display_name
        if profile.avatar_url:
            out["avatar_url"] = profile.avatar_url
        if profile.github_id:
            out["github_id"] = profile.github_id
    return out


def invite_key_to_dict(
    row: OrgInviteKeyRow,
    *,
    invite_key: str | None = None,
) -> dict[str, Any]:
    """Serialize invite key metadata for owner APIs.

    Pass ``invite_key`` only on create so the secret is returned once.
    List/revoke omit it; storage keeps hash + prefix only.
    """
    out: dict[str, Any] = {
        "key_id": row.key_id,
        "org_id": row.org_id,
        "token_prefix": row.token_prefix,
        "created_by": row.created_by,
        "max_uses": row.max_uses,
        "use_count": row.use_count,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "created_at": row.created_at,
        "active": row.revoked_at is None
        and (row.expires_at is None or row.expires_at > now())
        and (row.max_uses is None or row.use_count < row.max_uses),
    }
    if invite_key:
        out["invite_key"] = invite_key
    return out


def share_to_dict(row: ResultShareRow) -> dict[str, Any]:
    return {
        "result_kind": row.result_kind,
        "result_id": row.result_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "created_at": row.created_at,
    }


def request_to_dict(row: ResourceRequestRow) -> dict[str, Any]:
    out: dict[str, Any] = {
        "request_id": row.request_id,
        "kind": row.kind,
        "status": row.status,
        "suite_run_id": row.suite_run_id,
        "dataset_id": row.dataset_id,
        "applicant": row.applicant,
        "owner_org_id": row.owner_org_id,
        "created_at": row.created_at,
    }
    if row.agent_ref:
        out["agent_ref"] = row.agent_ref
    if row.canonical_model:
        out["canonical_model"] = row.canonical_model
    if row.decided_at is not None:
        out["decided_at"] = row.decided_at
    if row.decided_by:
        out["decided_by"] = row.decided_by
    return out


def suite_to_dict(
    row: SuiteResultRow,
    *,
    attempt_content_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Serialize suite result; never invent a suite-level PASS field.

    When *attempt_content_ids* is provided, each task_ref gains
    ``has_attempt_content`` (bool) for Hub Jobs deep-link readiness (#43).
    Callers must pass only attempt ids visible to the current principal
    (never invent true for private/unshared rows).
    """
    try:
        metrics = json.loads(row.metrics_json)
    except (json.JSONDecodeError, TypeError):
        metrics = {}
    try:
        task_refs = json.loads(row.tasks_json)
    except (json.JSONDecodeError, TypeError):
        task_refs = []
    if not isinstance(metrics, dict):
        metrics = {}
    if not isinstance(task_refs, list):
        task_refs = []
    if attempt_content_ids is not None:
        enriched: list[Any] = []
        for ref in task_refs:
            if not isinstance(ref, dict):
                enriched.append(ref)
                continue
            item = dict(ref)
            rid = item.get("run_id")
            rid_s = str(rid).strip() if rid is not None else ""
            item["has_attempt_content"] = bool(rid_s and rid_s in attempt_content_ids)
            enriched.append(item)
        task_refs = enriched
    out: dict[str, Any] = {
        "suite_run_id": row.suite_run_id,
        "dataset_id": row.dataset_id,
        "dataset_version": row.dataset_version,
        "visibility": row.visibility,
        "pass_rate": row.pass_rate,
        "mean_score": row.mean_score,
        "metrics": metrics,
        "task_refs": task_refs,
        "agent_label": row.agent_label,
        "model_label": row.model_label,
        "blob_digest": row.blob_digest,
        "size": row.size,
        "exit_code": row.exit_code,
        "created_at": row.created_at,
        "complete": bool(row.complete),
        "bound_kind": row.bound_kind or "unknown",
        # Explicit: no suite PASS authority
        "note": "per-task evaluator verdicts only; no suite-level PASS",
    }
    if row.task_set_digest:
        out["task_set_digest"] = row.task_set_digest
    if row.uploaded_by:
        out["uploaded_by"] = row.uploaded_by
    out["board_listed"] = bool(row.board_listed)
    # #42 config fingerprint projection (absent on legacy rows)
    try:
        cfg = json.loads(row.config_json or "{}")
    except (json.JSONDecodeError, TypeError):
        cfg = {}
    if isinstance(cfg, dict):
        if cfg.get("config_fingerprint"):
            out["config_fingerprint"] = cfg["config_fingerprint"]
        if "config_homogeneous" in cfg:
            out["config_homogeneous"] = bool(cfg["config_homogeneous"])
        actors = cfg.get("actors_summary")
        if isinstance(actors, list):
            out["actors_summary"] = actors
        # #59 secret-free job binding for Hub rehydrate
        overlay = cfg.get("job_overlay")
        if isinstance(overlay, dict) and overlay:
            out["job_overlay"] = overlay
        plugins = cfg.get("plugins")
        if isinstance(plugins, list) and plugins:
            out["plugins"] = plugins
    if any(
        isinstance(ref, dict) and isinstance(ref.get("previous"), list) and ref["previous"]
        for ref in task_refs
    ):
        out["amended"] = True
    return out


def _run_ids_from_tasks_json(tasks_json: str) -> list[str]:
    try:
        refs = json.loads(tasks_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(refs, list):
        return []
    out: list[str] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        rid = ref.get("run_id")
        if rid is None:
            continue
        text = str(rid).strip()
        if text:
            out.append(text)
    return out


def now() -> float:
    return time.time()
