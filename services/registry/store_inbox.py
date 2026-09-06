"""Inbox aggregate: requests, agent consent, canonical models, collect mode, hidden rows."""

from __future__ import annotations

import sqlite3
from typing import Any

from services.registry import queries as Q
from services.registry.clock import now
from services.registry.protocols import InboxStoreProtocol
from services.registry.rows import ResourceRequestRow
from services.registry.tokens import _normalize_user_id


class InboxStore(InboxStoreProtocol):
    """Inbox aggregate: requests, agent consent, canonical models, collect mode, hidden rows."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def _connect(self) -> Any:
        return self._adapter.connect()

    def _exec(self, conn: Any, sql: str, params: Any = ()) -> Any:
        return self._adapter.execute(conn, sql, params)

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
