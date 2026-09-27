"""Shared Protocols for Registry stores.

One narrow protocol per aggregate (package / result / org+user / inbox) plus
the token protocol. SQLite and Postgres implement the same contracts through
the shared dialect adapter; there is no god store protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from services.registry.auth.tokens import TokenInfo
    from services.registry.rows import (
        AttemptResultRow,
        ResourceRequestRow,
        ResultShareRow,
        SnapshotShareRow,
        SuiteResultRow,
    )


@runtime_checkable
class TokenStoreProtocol(Protocol):
    def hash_token(self, raw: str) -> str: ...

    def add(
        self,
        raw_token: str,
        scopes: frozenset[str] | set[str],
        *,
        github_user: str | None = None,
    ) -> None: ...

    def auth_for(self, raw_token: str | None) -> TokenInfo: ...

    def scopes_for(self, raw_token: str | None) -> frozenset[str]: ...



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

    def insert_snapshot_share(self, row: SnapshotShareRow) -> None: ...

    def get_snapshot_share(self, token: str) -> SnapshotShareRow | None: ...

    def find_snapshot_share(
        self, *, owner_user_id: str, suite_run_id: str, run_id: str
    ) -> SnapshotShareRow | None: ...

    def delete_snapshot_share(self, token: str) -> SnapshotShareRow: ...

    def count_snapshot_share_blob_refs(self, blob_digest: str) -> int: ...



@runtime_checkable
class InboxStoreProtocol(Protocol):
    def grant_agent_consent(
        self,
        *,
        suite_run_id: str,
        package_id: str,
        granted_by: str,
        source: str,
    ) -> None: ...

    def set_suite_canonical_model(
        self, suite_run_id: str, overlay_model: str, canonical_model: str
    ) -> None: ...

    def list_canonical_models_for_suites(
        self, suite_run_ids: list[str]
    ) -> dict[str, dict[str, str]]: ...

    def has_agent_consent(self, suite_run_id: str, package_id: str) -> bool: ...

    def list_agent_consents(self, suite_run_id: str) -> list[str]: ...

    def insert_resource_request(self, row: ResourceRequestRow) -> None: ...

    def get_resource_request(self, request_id: str) -> ResourceRequestRow | None: ...

    def get_pending_request(
        self, *, kind: str, suite_run_id: str, agent_ref: str = ""
    ) -> ResourceRequestRow | None: ...

    def list_resource_requests_by_ids(self, request_ids: list[str]) -> list[ResourceRequestRow]: ...

    def list_inbox_requests(
        self, *, org_ids: list[str], status: str | None = "pending"
    ) -> list[ResourceRequestRow]: ...

    def list_suite_requests(self, suite_run_id: str) -> list[ResourceRequestRow]: ...

    def update_resource_request_status(
        self, request_id: str, *, status: str, decided_by: str
    ) -> ResourceRequestRow: ...

    def list_agent_consents_for_suites(self, suite_run_ids: list[str]) -> dict[str, set[str]]: ...

    def get_performance_collect_mode(self, package_id: str) -> str | None: ...

    def list_performance_collect_modes(self) -> dict[str, str]: ...

    def set_performance_collect_mode(
        self, *, package_id: str, mode: str, updated_by: str
    ) -> None: ...

    def list_hidden_inbox_ids(self, user_id: str) -> set[str]: ...

    def hide_inbox_requests(self, *, user_id: str, request_ids: list[str]) -> None: ...

    def revoke_agent_consent(self, *, suite_run_id: str, package_id: str) -> None: ...
