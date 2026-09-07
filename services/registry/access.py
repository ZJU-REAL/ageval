"""Central AccessPolicy for Registry HTTP authorization.

ACL decisions live here so handler routes cannot silently omit a helper call.
Response writing stays in the handler; this module only answers questions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from services.registry.rows import DraftRow, ReleaseRow
from services.registry.tokens import TokenInfo

OrgOwnerStatus = Literal["ok", "not_found", "unauthorized", "forbidden"]


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    """Single authorization surface; reads the three aggregates it authorizes."""

    orgs: Any
    packages: Any
    results: Any

    @staticmethod
    def is_admin(scopes: frozenset[str]) -> bool:
        return "admin" in scopes

    def visible_package(self, row: ReleaseRow, auth: TokenInfo) -> bool:
        if row.visibility == "public":
            return True
        if self.is_admin(auth.scopes):
            return True
        if not auth.user_id or not row.org_id:
            return False
        return self.orgs.membership(row.org_id, auth.user_id) is not None

    def visible_result(
        self,
        *,
        result_kind: str,
        result_id: str,
        visibility: str,
        uploaded_by: str,
        auth: TokenInfo,
    ) -> bool:
        if visibility == "public":
            return True
        if self.is_admin(auth.scopes):
            return True
        if not auth.user_id:
            return False
        if uploaded_by and uploaded_by == auth.user_id:
            return True
        orgs = self.orgs.user_org_ids(auth.user_id) if auth.user_id else set()
        return self.results.result_shared_with_user(
            result_kind=result_kind,
            result_id=result_id,
            user_id=auth.user_id,
            user_orgs=orgs,
        )

    def entitled_to_draft(self, draft: DraftRow, auth: TokenInfo) -> bool:
        if self.is_admin(auth.scopes):
            return True
        if not auth.user_id:
            return False
        acl = self.packages.dataset_acl(draft.dataset_id, auth.user_id)
        if acl is not None:
            return True
        return bool(draft.org_id and self.orgs.membership(draft.org_id, auth.user_id) is not None)

    def can_write_draft(self, draft: DraftRow | None, *, org_id: str, auth: TokenInfo) -> bool:
        if self.is_admin(auth.scopes):
            return True
        if not auth.user_id:
            return False
        if draft is None:
            return self.orgs.membership(org_id, auth.user_id) is not None
        acl = self.packages.dataset_acl(draft.dataset_id, auth.user_id)
        return bool(acl is not None and acl.role in {"owner", "collaborator"})

    def can_release_draft(self, draft: DraftRow, auth: TokenInfo) -> bool:
        if self.is_admin(auth.scopes):
            return True
        if not auth.user_id:
            return False
        acl = self.packages.dataset_acl(draft.dataset_id, auth.user_id)
        if acl is not None and acl.role == "owner":
            return True
        if draft.org_id:
            mem = self.orgs.membership(draft.org_id, auth.user_id)
            if mem is not None and mem.role == "owner":
                return True
        return False

    def can_manage_package(self, row: ReleaseRow, auth: TokenInfo) -> bool:
        if self.is_admin(auth.scopes):
            return True
        if not auth.user_id or not row.org_id:
            return False
        mem = self.orgs.membership(row.org_id, auth.user_id)
        return mem is not None and mem.role == "owner"

    def can_manage_result(
        self,
        result_kind: str,
        result_id: str,
        auth: TokenInfo,
        *,
        for_read: bool,
    ) -> bool:
        if result_kind == "attempt":
            row = self.results.get_attempt(result_id)
            if row is None:
                return False
            if for_read:
                return self.visible_result(
                    result_kind="attempt",
                    result_id=row.run_id,
                    visibility=row.visibility,
                    uploaded_by=row.uploaded_by,
                    auth=auth,
                )
            return self.is_admin(auth.scopes) or (
                bool(auth.user_id) and row.uploaded_by == auth.user_id
            )
        row_s = self.results.get_suite(result_id)
        if row_s is None:
            return False
        if for_read:
            return self.visible_result(
                result_kind="suite",
                result_id=row_s.suite_run_id,
                visibility=row_s.visibility,
                uploaded_by=row_s.uploaded_by,
                auth=auth,
            )
        return self.is_admin(auth.scopes) or (
            bool(auth.user_id) and row_s.uploaded_by == auth.user_id
        )

    def enforce_route_access(
        self,
        access: str,
        auth: TokenInfo,
        *,
        kwargs: dict[str, Any],
    ) -> tuple[int, dict[str, str]] | None:
        """Return ``(status, body)`` when the route is denied; ``None`` if allowed."""
        if access == "none":
            return None
        if access == "bearer":
            return None
        if access == "publish":
            if "registry:publish" not in auth.scopes and "admin" not in auth.scopes:
                return 401, {"error": "unauthorized", "message": "publish scope required"}
            if not auth.user_id:
                return 401, {
                    "error": "unauthorized",
                    "message": "publish requires authenticated user identity",
                }
            return None
        if access == "results_upload":
            if "results:upload" not in auth.scopes and "admin" not in auth.scopes:
                return 401, {"error": "unauthorized", "message": "results:upload scope required"}
            if not auth.user_id:
                return 401, {
                    "error": "unauthorized",
                    "message": "upload requires authenticated user identity",
                }
            return None
        if access == "org_owner":
            org_id = str(kwargs.get("org_id") or "")
            if not org_id:
                dataset_id = str(kwargs.get("dataset_id") or "")
                version = str(kwargs.get("version") or "")
                if dataset_id and version:
                    row = self.packages.get_by_version(dataset_id, version)
                    if row is None:
                        return 404, {"error": "not_found", "message": "package not found"}
                    if not self.can_manage_package(row, auth):
                        return 403, {"error": "forbidden", "message": "org owner required"}
                    return None
                return 400, {"error": "invalid_request", "message": "org_id required"}
            status = self.org_owner_status(org_id=org_id, auth=auth)
            if status == "ok":
                return None
            if status == "not_found":
                return 404, {"error": "not_found", "message": "org not found"}
            if status == "unauthorized":
                return 401, {"error": "unauthorized", "message": "authentication required"}
            return 403, {"error": "forbidden", "message": "org owner required"}
        if access == "result_manage":
            result_kind = str(kwargs.get("result_kind") or "")
            result_id = str(
                kwargs.get("result_id") or kwargs.get("run_id") or kwargs.get("suite_run_id") or ""
            )
            if not result_kind:
                result_kind = "attempt" if kwargs.get("run_id") else "suite"
            if not result_id:
                return 400, {"error": "invalid_request", "message": "result id required"}
            if not self.can_manage_result(result_kind, result_id, auth, for_read=False):
                return 403, {"error": "forbidden", "message": "result owner required"}
            return None
        return 500, {"error": "internal", "message": f"unknown access {access}"}

    def org_owner_status(self, *, org_id: str, auth: TokenInfo) -> OrgOwnerStatus:
        org = self.orgs.get_org(org_id)
        if org is None:
            return "not_found"
        if self.is_admin(auth.scopes):
            return "ok"
        if not auth.user_id:
            return "unauthorized"
        mem = self.orgs.membership(org_id, auth.user_id)
        if mem is None or mem.role != "owner":
            return "forbidden"
        return "ok"
