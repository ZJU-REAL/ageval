"""Result aggregate persistence: attempt results, suite results, result shares."""

from __future__ import annotations

import sqlite3
from typing import Any

from services.registry import queries as Q
from services.registry.clock import now
from services.registry.protocols import ResultStoreProtocol
from services.registry.rows import (
    AttemptResultRow,
    ResultShareRow,
    SuiteResultRow,
)


class ResultStore(ResultStoreProtocol):
    """Result aggregate persistence: attempt results, suite results, result shares."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def _connect(self) -> Any:
        return self._adapter.connect()

    def _exec(self, conn: Any, sql: str, params: Any = ()) -> Any:
        return self._adapter.execute(conn, sql, params)

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
