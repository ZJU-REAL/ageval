"""Result store protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from services.registry.results.rows import (
        AttemptResultRow,
        ResultShareRow,
        SuiteResultRow,
    )


@runtime_checkable
class ResultStoreProtocol(Protocol):
    def insert_attempt(self, row: AttemptResultRow) -> None: ...

    def get_attempt(self, run_id: str) -> AttemptResultRow | None: ...

    def attempts_for_ids(self, run_ids: list[str] | set[str]) -> list[AttemptResultRow]: ...

    def existing_attempt_ids(self, run_ids: list[str] | set[str]) -> set[str]: ...

    def list_attempts(
        self,
        *,
        dataset_id: str | None = None,
        task_id: str | None = None,
        standalone: bool = False,
        include_private: bool = False,
    ) -> list[AttemptResultRow]: ...

    def insert_suite(self, row: SuiteResultRow) -> None: ...

    def get_suite(self, suite_run_id: str) -> SuiteResultRow | None: ...

    def list_suites(
        self,
        *,
        dataset_id: str | None = None,
        include_private: bool = False,
    ) -> list[SuiteResultRow]: ...

    def delete_attempt(self, run_id: str) -> AttemptResultRow: ...

    def set_attempt_visibility(self, run_id: str, visibility: str) -> AttemptResultRow: ...

    def delete_suite(self, suite_run_id: str) -> SuiteResultRow: ...

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
    ) -> SuiteResultRow: ...

    def update_suite_config_json(self, suite_run_id: str, config_json: str) -> SuiteResultRow: ...

    def set_suite_board_listed(self, suite_run_id: str, listed: bool) -> SuiteResultRow: ...

    def set_suite_visibility(self, suite_run_id: str, visibility: str) -> SuiteResultRow: ...

    def list_attempts_for_suite(self, suite_run_id: str) -> list[AttemptResultRow]: ...

    def count_attempt_blob_refs(self, blob_digest: str) -> int: ...

    def count_suite_blob_refs(self, blob_digest: str) -> int: ...

    def add_result_share(
        self,
        *,
        result_kind: str,
        result_id: str,
        target_type: str,
        target_id: str,
    ) -> ResultShareRow: ...

    def remove_result_share(
        self,
        *,
        result_kind: str,
        result_id: str,
        target_type: str,
        target_id: str,
    ) -> None: ...

    def list_result_shares(self, *, result_kind: str, result_id: str) -> list[ResultShareRow]: ...

    def result_shared_with_user(
        self,
        *,
        result_kind: str,
        result_id: str,
        user_id: str,
        user_orgs: set[str],
    ) -> bool: ...

