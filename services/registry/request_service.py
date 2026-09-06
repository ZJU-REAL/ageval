"""Listing and performance requests. Approve runs existing writes only."""

from __future__ import annotations

import secrets
from typing import Any

from services.registry.dataset import BOUND_RELEASE
from services.registry.errors import RegistryAppError
from services.registry.maintainers import MAINTAINER_INBOX_ORG, auth_is_maintainer
from services.registry.store import ResourceRequestRow, TokenInfo, now, request_to_dict

REQUEST_KINDS = frozenset({"leaderboard_list", "agent_performance"})
REQUEST_STATUSES = frozenset({"pending", "approved", "rejected"})
DECIDE_ACTIONS = frozenset({"approve", "reject"})


class RequestService:
    def __init__(
        self,
        inbox: Any,
        orgs: Any,
        packages: Any,
        results: Any,
        access: Any,
        results_api: Any,
    ) -> None:
        self.inbox_store = inbox
        self.orgs = orgs
        self.packages = packages
        self.results = results
        self.access = access
        self.results_api = results_api

    def apply(
        self,
        *,
        kind: str,
        suite_run_id: str,
        auth: TokenInfo,
        agent: str | None = None,
        canonical_model: str | None = None,
    ) -> dict[str, Any]:
        kind = kind.strip()
        if kind not in REQUEST_KINDS:
            raise RegistryAppError("invalid_request", "unknown request kind", http_status=400)
        if not auth.user_id:
            raise RegistryAppError("unauthorized", "authentication required", http_status=401)
        suite = self.results.get_suite(suite_run_id)
        if suite is None or not self.access.can_manage_result(
            "suite", suite_run_id, auth, for_read=False
        ):
            raise RegistryAppError("not_found", "suite not found", http_status=404)
        if kind == "leaderboard_list":
            return self._apply_listing(suite, auth)
        return self._apply_performance(suite, auth, agent or "", canonical_model or "")

    def inbox(self, *, auth: TokenInfo) -> dict[str, Any]:
        org_ids = self._owner_org_ids(auth)
        if auth_is_maintainer(auth):
            org_ids.add(MAINTAINER_INBOX_ORG)
        rows = self.inbox_store.list_inbox_requests(org_ids=list(org_ids), status=None)
        hidden = self.inbox_store.list_hidden_inbox_ids(auth.user_id or "")
        items = [request_to_dict(r) for r in rows if r.request_id not in hidden]
        return {"items": items}

    def list_for_suite(self, *, suite_run_id: str, auth: TokenInfo) -> dict[str, Any]:
        suite = self.results.get_suite(suite_run_id)
        if suite is None or not self.access.can_manage_result(
            "suite", suite_run_id, auth, for_read=True
        ):
            raise RegistryAppError("not_found", "suite not found", http_status=404)
        rows = self.inbox_store.list_suite_requests(suite_run_id)
        owner_orgs = self._owner_org_ids(auth)
        is_uploader = bool(auth.user_id) and suite.uploaded_by == auth.user_id
        maintainer = auth_is_maintainer(auth)
        items = [
            request_to_dict(r)
            for r in rows
            if is_uploader
            or r.owner_org_id in owner_orgs
            or (maintainer and r.owner_org_id == MAINTAINER_INBOX_ORG)
            or self.access.is_admin(auth.scopes)
        ]
        return {"items": items}

    def decide(
        self,
        *,
        request_ids: list[str],
        action: str,
        auth: TokenInfo,
        canonical_model: str | None = None,
    ) -> dict[str, Any]:
        action = action.strip()
        if action not in DECIDE_ACTIONS:
            raise RegistryAppError(
                "invalid_request", "action must be approve or reject", http_status=400
            )
        ids = [i.strip() for i in request_ids if isinstance(i, str) and i.strip()]
        if not ids:
            raise RegistryAppError("invalid_request", "ids required", http_status=400)
        rows = self.inbox_store.list_resource_requests_by_ids(ids)
        by_id = {r.request_id: r for r in rows}
        for rid in ids:
            row = by_id.get(rid)
            if row is None or row.status != "pending" or not self._can_decide(row, auth):
                raise RegistryAppError("not_found", "request not found", http_status=404)
        if action == "approve":
            for rid in ids:
                row = by_id[rid]
                if row.kind != "agent_performance":
                    continue
                chosen = (canonical_model or row.canonical_model or "").strip()
                if not chosen:
                    raise RegistryAppError(
                        "invalid_request",
                        "canonical_model required",
                        http_status=400,
                    )
        decided: list[dict[str, Any]] = []
        for rid in ids:
            row = by_id[rid]
            if action == "approve":
                self._approve(row, auth, canonical_model=canonical_model)
            updated = self.inbox_store.update_resource_request_status(
                rid,
                status="approved" if action == "approve" else "rejected",
                decided_by=auth.user_id or "",
            )
            decided.append(request_to_dict(updated))
        return {"items": decided, "action": action}

    def hide(
        self,
        *,
        request_ids: list[str],
        auth: TokenInfo,
    ) -> dict[str, Any]:
        if not auth.user_id:
            raise RegistryAppError("unauthorized", "authentication required", http_status=401)
        ids = [i.strip() for i in request_ids if isinstance(i, str) and i.strip()]
        if not ids:
            raise RegistryAppError("invalid_request", "ids required", http_status=400)
        visible = {
            str(item["request_id"]): item
            for item in self.inbox(auth=auth)["items"]
            if isinstance(item, dict)
        }
        for rid in ids:
            row = visible.get(rid)
            if row is None or str(row.get("status") or "") == "pending":
                raise RegistryAppError("not_found", "request not found", http_status=404)
        self.inbox_store.hide_inbox_requests(user_id=auth.user_id, request_ids=ids)
        return {"ok": True, "ids": ids}

    def _apply_listing(self, suite: Any, auth: TokenInfo) -> dict[str, Any]:
        if not suite.complete or suite.bound_kind != BOUND_RELEASE:
            raise RegistryAppError(
                "invalid_request",
                "listing requires a complete release-bound suite",
                http_status=400,
            )
        org_id = self._dataset_org_id(suite.dataset_id, suite.dataset_version)
        pending = self.inbox_store.get_pending_request(
            kind="leaderboard_list", suite_run_id=suite.suite_run_id, agent_ref=""
        )
        if pending is not None:
            raise RegistryAppError("conflict", "listing request already pending", http_status=409)
        if suite.board_listed:
            raise RegistryAppError("conflict", "suite is already listed", http_status=409)
        row = self._new_row(
            kind="leaderboard_list",
            suite=suite,
            applicant=auth.user_id or "",
            owner_org_id=org_id,
            agent_ref="",
        )
        self.inbox_store.insert_resource_request(row)
        return request_to_dict(row)

    def _apply_performance(
        self, suite: Any, auth: TokenInfo, agent: str, canonical_model: str
    ) -> dict[str, Any]:
        from services.registry.store import package_kind_for_media_type

        from ageval.application.suite.attach_agent_ref import (
            AttachAgentRefError,
            load_builtin_attach,
            parse_published_agent_spec,
        )

        try:
            spec_role, package_id, version = parse_published_agent_spec(agent)
            builtin = load_builtin_attach(package_id, version)
        except AttachAgentRefError as exc:
            raise RegistryAppError(exc.error_code, exc.message, http_status=400) from exc
        stored_ref = (
            f"{spec_role}={package_id}@{version}" if spec_role else f"{package_id}@{version}"
        )
        stored_canonical = canonical_model.strip()
        if builtin is not None:
            if auth_is_maintainer(auth):
                attached = self.results_api.attach_agent(
                    suite_run_id=suite.suite_run_id,
                    agent=agent,
                    auth=auth,
                    grant_consent=True,
                    canonical_model=stored_canonical,
                )
                attached["request"] = None
                attached["direct_attach"] = True
                return attached
            pending = self.inbox_store.get_pending_request(
                kind="agent_performance",
                suite_run_id=suite.suite_run_id,
                agent_ref=stored_ref,
            )
            if pending is not None:
                raise RegistryAppError(
                    "conflict", "performance request already pending", http_status=409
                )
            row = self._new_row(
                kind="agent_performance",
                suite=suite,
                applicant=auth.user_id or "",
                owner_org_id=MAINTAINER_INBOX_ORG,
                agent_ref=stored_ref,
                canonical_model=stored_canonical,
            )
            self.inbox_store.insert_resource_request(row)
            return request_to_dict(row)
        release = self.packages.get_by_version(package_id, version)
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
        owner_org = (release.org_id or "").strip()
        if not owner_org:
            raise RegistryAppError("invalid_request", "agent package has no org", http_status=400)
        if self.access.org_owner_status(org_id=owner_org, auth=auth) == "ok":
            attached = self.results_api.attach_agent(
                suite_run_id=suite.suite_run_id,
                agent=agent,
                auth=auth,
                grant_consent=True,
                canonical_model=stored_canonical,
            )
            attached["request"] = None
            attached["direct_attach"] = True
            return attached
        pending = self.inbox_store.get_pending_request(
            kind="agent_performance",
            suite_run_id=suite.suite_run_id,
            agent_ref=stored_ref,
        )
        if pending is not None:
            raise RegistryAppError(
                "conflict", "performance request already pending", http_status=409
            )
        row = self._new_row(
            kind="agent_performance",
            suite=suite,
            applicant=auth.user_id or "",
            owner_org_id=owner_org,
            agent_ref=stored_ref,
            canonical_model=stored_canonical,
        )
        self.inbox_store.insert_resource_request(row)
        return request_to_dict(row)

    def _approve(
        self,
        row: ResourceRequestRow,
        auth: TokenInfo,
        *,
        canonical_model: str | None = None,
    ) -> None:
        try:
            if row.kind == "leaderboard_list":
                self.results.set_suite_board_listed(row.suite_run_id, True)
                return
            chosen = (canonical_model or row.canonical_model or "").strip()
            if not chosen:
                raise RegistryAppError(
                    "invalid_request",
                    "canonical_model required",
                    http_status=400,
                )
            self.results_api.attach_agent(
                suite_run_id=row.suite_run_id,
                agent=row.agent_ref,
                auth=auth,
                grant_consent=True,
                skip_owner_check=True,
                canonical_model=chosen,
            )
        except LookupError as exc:
            raise RegistryAppError("not_found", "suite not found", http_status=404) from exc

    def _can_decide(self, row: ResourceRequestRow, auth: TokenInfo) -> bool:
        if row.owner_org_id == MAINTAINER_INBOX_ORG:
            return auth_is_maintainer(auth)
        return row.owner_org_id in self._owner_org_ids(auth)

    def _dataset_org_id(self, dataset_id: str, version: str) -> str:
        release = self.packages.get_by_version(dataset_id, version)
        if release is None or not release.org_id:
            raise RegistryAppError(
                "invalid_request",
                "dataset package org is missing",
                http_status=400,
            )
        return release.org_id

    def _owner_org_ids(self, auth: TokenInfo) -> set[str]:
        if not auth.user_id:
            return set()
        out: set[str] = set()
        for org_id in self.orgs.user_org_ids(auth.user_id):
            mem = self.orgs.membership(org_id, auth.user_id)
            if mem is not None and mem.role == "owner":
                out.add(org_id)
        return out

    def _new_row(
        self,
        *,
        kind: str,
        suite: Any,
        applicant: str,
        owner_org_id: str,
        agent_ref: str,
        canonical_model: str = "",
    ) -> ResourceRequestRow:
        return ResourceRequestRow(
            request_id=f"req_{secrets.token_hex(12)}",
            kind=kind,
            status="pending",
            suite_run_id=suite.suite_run_id,
            dataset_id=suite.dataset_id,
            applicant=applicant,
            owner_org_id=owner_org_id,
            agent_ref=agent_ref,
            created_at=now(),
            canonical_model=canonical_model.strip(),
        )
