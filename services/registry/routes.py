"""Declarative Registry HTTP route table.

Handlers remain methods on the BaseHTTPRequestHandler subclass; this module
owns *which* path matches *which* handler so ACL call sites stay discoverable
next to the route name rather than buried in do_GET/do_POST chains.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

RouteAccess = Literal[
    "none",
    "bearer",
    "publish",
    "results_upload",
    "org_owner",
    "result_manage",
]


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    name: str
    access: RouteAccess
    exact: str | None = None
    pattern: str | None = None
    groups: tuple[str, ...] = ()
    # Extra kwargs merged into the handler call (e.g. result_kind).
    fixed: Mapping[str, Any] | None = None
    # Optional path filter after a regex match (package id vs versions subpaths).
    predicate: Callable[[str], bool] | None = None
    # When True, skip bearer resolution. Prefer ``access``; skip_auth is derived.
    skip_auth: bool = False
    # Pass query-string dict as ``qs=``.
    pass_qs: bool = False

    def __post_init__(self) -> None:
        allowed = {"none", "bearer", "publish", "results_upload", "org_owner", "result_manage"}
        if self.access not in allowed:
            raise ValueError(f"invalid route access: {self.access!r}")
        if self.skip_auth and self.access != "none":
            raise ValueError("skip_auth=True is only valid when access='none'")
        object.__setattr__(self, "skip_auth", self.access == "none")


def _package_id_list_ok(path: str) -> bool:
    rest = path[len("/v1/packages/") :]
    if not rest or "/versions/" in rest or "/by-digest/" in rest:
        return False
    return not rest.endswith("/favorite") and not rest.endswith("/release")


ROUTES: tuple[Route, ...] = (
    # GET
    Route("GET", "health", access="none", exact="/health"),
    Route(
        "GET",
        "get_user",
        access="none",
        pattern=r"/v1/users/([^/]+)",
        groups=("user_id",),
    ),
    Route("GET", "list_orgs", access="bearer", exact="/v1/orgs"),
    Route(
        "GET",
        "list_invite_keys",
        access="org_owner",
        pattern=r"/v1/orgs/([^/]+)/invite-keys",
        groups=("org_id",),
    ),
    Route(
        "GET",
        "list_org_members",
        access="bearer",
        pattern=r"/v1/orgs/([^/]+)/members",
        groups=("org_id",),
    ),
    Route("GET", "get_org", access="bearer", pattern=r"/v1/orgs/([^/]+)", groups=("org_id",)),
    Route("GET", "list_packages", access="bearer", exact="/v1/packages", pass_qs=True),
    Route(
        "GET",
        "list_package_versions",
        access="bearer",
        pattern=r"/v1/packages/([^/]+(?:/[^/]+)*)",
        groups=("dataset_id",),
        predicate=_package_id_list_ok,
    ),
    Route(
        "GET",
        "serve_meta",
        access="bearer",
        pattern=r"/v1/packages/(.+)/versions/([^/]+)",
        groups=("dataset_id", "version"),
        fixed={"package_digest": None},
    ),
    Route(
        "GET",
        "serve_content",
        access="bearer",
        pattern=r"/v1/packages/(.+)/by-digest/(sha256:[0-9a-f]{64})/content",
        groups=("dataset_id", "package_digest"),
    ),
    Route(
        "GET",
        "serve_package_files_list",
        access="bearer",
        pattern=r"/v1/packages/(.+)/by-digest/(sha256:[0-9a-f]{64})/files",
        groups=("dataset_id", "package_digest"),
    ),
    Route(
        "GET",
        "serve_package_file",
        access="bearer",
        pattern=r"/v1/packages/(.+)/by-digest/(sha256:[0-9a-f]{64})/files/(.+)",
        groups=("dataset_id", "package_digest", "file_path"),
    ),
    Route(
        "GET",
        "serve_package_files_list",
        access="bearer",
        pattern=r"/v1/packages/(.+)/versions/([^/]+)/files",
        groups=("dataset_id", "version"),
    ),
    Route(
        "GET",
        "serve_package_file",
        access="bearer",
        pattern=r"/v1/packages/(.+)/versions/([^/]+)/files/(.+)",
        groups=("dataset_id", "version", "file_path"),
    ),
    Route(
        "GET",
        "serve_meta",
        access="bearer",
        pattern=r"/v1/packages/(.+)/by-digest/(sha256:[0-9a-f]{64})",
        groups=("dataset_id", "package_digest"),
        fixed={"version": None},
    ),
    Route("GET", "list_attempts", access="bearer", exact="/v1/results/attempts", pass_qs=True),
    Route(
        "GET",
        "serve_attempt_content",
        access="bearer",
        pattern=r"/v1/results/attempts/([^/]+)/content",
        groups=("run_id",),
    ),
    Route(
        "GET",
        "serve_attempt_file",
        access="bearer",
        pattern=r"/v1/results/attempts/([^/]+)/files/(.+)",
        groups=("run_id", "file_path"),
    ),
    Route(
        "GET",
        "serve_attempt_files_list",
        access="bearer",
        pattern=r"/v1/results/attempts/([^/]+)/files",
        groups=("run_id",),
    ),
    Route(
        "GET",
        "list_result_shares",
        access="result_manage",
        pattern=r"/v1/results/attempts/([^/]+)/shares",
        groups=("result_id",),
        fixed={"result_kind": "attempt"},
    ),
    Route(
        "GET",
        "serve_attempt_meta",
        access="bearer",
        pattern=r"/v1/results/attempts/([^/]+)",
        groups=("run_id",),
    ),
    Route("GET", "list_suites", access="bearer", exact="/v1/results/suites", pass_qs=True),
    Route("GET", "list_requests", access="bearer", exact="/v1/requests", pass_qs=True),
    Route(
        "GET",
        "serve_suite_content",
        access="bearer",
        pattern=r"/v1/results/suites/([^/]+)/content",
        groups=("suite_run_id",),
    ),
    Route(
        "GET",
        "list_result_shares",
        access="result_manage",
        pattern=r"/v1/results/suites/([^/]+)/shares",
        groups=("result_id",),
        fixed={"result_kind": "suite"},
    ),
    Route(
        "GET",
        "serve_suite_meta",
        access="bearer",
        pattern=r"/v1/results/suites/([^/]+)",
        groups=("suite_run_id",),
    ),
    # POST
    Route(
        "POST",
        "auth_device_code",
        access="none",
        exact="/v1/auth/github/device/code",
    ),
    Route(
        "POST",
        "auth_device_poll",
        access="none",
        exact="/v1/auth/github/device/poll",
    ),
    Route("POST", "auth_web_start", access="none", exact="/v1/auth/github/web/start"),
    Route(
        "POST",
        "auth_web_callback",
        access="none",
        exact="/v1/auth/github/web/callback",
    ),
    Route("POST", "create_org", access="bearer", exact="/v1/orgs"),
    Route("POST", "join_org_with_invite", access="bearer", exact="/v1/orgs/join"),
    Route(
        "POST",
        "claim_org",
        access="bearer",
        pattern=r"/v1/orgs/([^/]+)/claim",
        groups=("org_id",),
    ),
    Route(
        "POST",
        "leave_org",
        access="bearer",
        pattern=r"/v1/orgs/([^/]+)/leave",
        groups=("org_id",),
    ),
    Route(
        "POST",
        "create_invite_key",
        access="org_owner",
        pattern=r"/v1/orgs/([^/]+)/invite-keys",
        groups=("org_id",),
    ),
    Route(
        "POST",
        "add_org_member",
        access="org_owner",
        pattern=r"/v1/orgs/([^/]+)/members",
        groups=("org_id",),
    ),
    Route(
        "POST",
        "transfer_org",
        access="bearer",
        pattern=r"/v1/orgs/([^/]+)/transfer",
        groups=("org_id",),
    ),
    Route("POST", "publish_package", access="publish", exact="/v1/packages"),
    Route(
        "POST",
        "release_draft",
        access="publish",
        pattern=r"/v1/packages/(.+)/release",
        groups=("dataset_id",),
    ),
    Route(
        "POST",
        "put_package_favorite",
        access="bearer",
        pattern=r"/v1/packages/(.+)/favorite",
        groups=("dataset_id",),
    ),
    Route(
        "POST",
        "upload_attempt",
        access="results_upload",
        exact="/v1/results/attempts",
    ),
    Route("POST", "upload_suite", access="results_upload", exact="/v1/results/suites"),
    Route("POST", "apply_request", access="bearer", exact="/v1/requests"),
    Route("POST", "decide_requests", access="bearer", exact="/v1/requests/decide"),
    Route(
        "POST",
        "append_suite_slot",
        access="results_upload",
        pattern=r"/v1/results/suites/([^/]+)/slots",
        groups=("suite_run_id",),
    ),
    Route(
        "POST",
        "add_result_share",
        access="result_manage",
        pattern=r"/v1/results/attempts/([^/]+)/shares",
        groups=("result_id",),
        fixed={"result_kind": "attempt"},
    ),
    Route(
        "POST",
        "add_result_share",
        access="result_manage",
        pattern=r"/v1/results/suites/([^/]+)/shares",
        groups=("result_id",),
        fixed={"result_kind": "suite"},
    ),
    # DELETE
    Route(
        "DELETE",
        "revoke_invite_key",
        access="org_owner",
        pattern=r"/v1/orgs/([^/]+)/invite-keys/([^/]+)",
        groups=("org_id", "key_id"),
    ),
    Route(
        "DELETE",
        "remove_org_member",
        access="org_owner",
        pattern=r"/v1/orgs/([^/]+)/members/([^/]+)",
        groups=("org_id", "user_id"),
    ),
    Route(
        "DELETE",
        "delete_org",
        access="org_owner",
        pattern=r"/v1/orgs/([^/]+)",
        groups=("org_id",),
    ),
    Route(
        "DELETE",
        "remove_result_share",
        access="result_manage",
        pattern=r"/v1/results/attempts/([^/]+)/shares",
        groups=("result_id",),
        fixed={"result_kind": "attempt"},
    ),
    Route(
        "DELETE",
        "remove_result_share",
        access="result_manage",
        pattern=r"/v1/results/suites/([^/]+)/shares",
        groups=("result_id",),
        fixed={"result_kind": "suite"},
    ),
    Route(
        "DELETE",
        "delete_attempt",
        access="result_manage",
        pattern=r"/v1/results/attempts/([^/]+)",
        groups=("run_id",),
    ),
    Route(
        "DELETE",
        "delete_suite",
        access="result_manage",
        pattern=r"/v1/results/suites/([^/]+)",
        groups=("suite_run_id",),
        pass_qs=True,
    ),
    Route(
        "DELETE",
        "delete_package_release",
        access="org_owner",
        pattern=r"/v1/packages/(.+)/versions/([^/]+)",
        groups=("dataset_id", "version"),
    ),
    Route(
        "DELETE",
        "delete_package_favorite",
        access="bearer",
        pattern=r"/v1/packages/(.+)/favorite",
        groups=("dataset_id",),
    ),
    # PATCH
    Route(
        "PATCH",
        "patch_org_member",
        access="org_owner",
        pattern=r"/v1/orgs/([^/]+)/members/([^/]+)",
        groups=("org_id", "user_id"),
    ),
    Route(
        "PATCH",
        "patch_attempt",
        access="result_manage",
        pattern=r"/v1/results/attempts/([^/]+)",
        groups=("run_id",),
    ),
    Route(
        "PATCH",
        "attach_suite_agent",
        access="result_manage",
        pattern=r"/v1/results/suites/([^/]+)/agent-ref",
        groups=("suite_run_id",),
    ),
    Route(
        "PATCH",
        "patch_suite",
        access="result_manage",
        pattern=r"/v1/results/suites/([^/]+)",
        groups=("suite_run_id",),
    ),
    Route(
        "PATCH",
        "patch_package_release",
        access="org_owner",
        pattern=r"/v1/packages/(.+)/versions/([^/]+)",
        groups=("dataset_id", "version"),
    ),
    Route(
        "PATCH",
        "patch_org",
        access="org_owner",
        pattern=r"/v1/orgs/([^/]+)",
        groups=("org_id",),
    ),
    Route(
        "PATCH",
        "patch_user",
        access="bearer",
        pattern=r"/v1/users/([^/]+)",
        groups=("user_id",),
    ),
    Route(
        "PATCH",
        "patch_package_display_name",
        access="bearer",
        pattern=r"/v1/packages/([^/]+(?:/[^/]+)*)",
        groups=("dataset_id",),
        predicate=_package_id_list_ok,
    ),
)


def match_route(method: str, path: str) -> tuple[Route, dict[str, Any]] | None:
    """Return the first matching route and captured kwargs (excluding auth/qs)."""
    for route in ROUTES:
        if route.method != method:
            continue
        if route.exact is not None:
            if path == route.exact:
                kwargs = dict(route.fixed or {})
                return route, kwargs
            continue
        if route.pattern is None:
            continue
        m = re.fullmatch(route.pattern, path)
        if not m:
            continue
        if route.predicate is not None and not route.predicate(path):
            continue
        kwargs = dict(route.fixed or {})
        for i, name in enumerate(route.groups):
            kwargs[name] = m.group(i + 1)
        return route, kwargs
    return None
