"""Route table requires an access policy; dispatch cannot skip ACL."""

from __future__ import annotations

import pytest
from services.registry.access import AccessPolicy
from services.registry.routes import ROUTES, Route
from services.registry.store import TokenInfo


def test_every_route_declares_access() -> None:
    allowed = {"none", "bearer", "publish", "results_upload", "org_owner", "result_manage"}
    for route in ROUTES:
        assert route.access in allowed, route.name


def test_route_without_access_cannot_be_constructed() -> None:
    with pytest.raises(TypeError):
        Route("GET", "oops", exact="/oops")  # type: ignore[call-arg]


def test_publish_access_requires_scope() -> None:
    policy = AccessPolicy(orgs=object(), packages=object(), results=object())
    denied = policy.enforce_route_access(
        "publish",
        TokenInfo(scopes=frozenset({"read"}), user_id="alice"),
        kwargs={},
    )
    assert denied is not None
    assert denied[0] == 401
    ok = policy.enforce_route_access(
        "publish",
        TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice"),
        kwargs={},
    )
    assert ok is None


def test_skip_auth_is_derived_from_access() -> None:
    none = Route("GET", "health", access="none", exact="/health")
    assert none.skip_auth is True
    bearer = Route("GET", "list", access="bearer", exact="/v1/packages")
    assert bearer.skip_auth is False
    with pytest.raises(ValueError, match="skip_auth"):
        Route("POST", "publish", access="publish", exact="/v1/packages", skip_auth=True)


def test_bearer_helper_is_only_used_by_dispatch() -> None:
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[2] / "services" / "registry" / "http_api.py"
    ).read_text(encoding="utf-8")
    assert text.count("_bearer(") == 2
