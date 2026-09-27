"""Inbox store protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from services.registry.inbox.rows import ResourceRequestRow


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
