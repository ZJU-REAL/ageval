"""Public user GET: official is Registry-computed; private orgs stay hidden."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from services.registry.app import build_default_state, make_handler
from services.registry.errors import RegistryAppError
from services.registry.store import DEFAULT_LOGIN_SCOPES
from services.registry.store_schema import (
    open_sqlite_stores,
)
from services.registry.user_service import UserService


def _users(tmp_path: Path) -> UserService:
    return UserService(open_sqlite_stores(tmp_path / "meta.sqlite3").orgs)


def test_official_member_is_marked(tmp_path: Path) -> None:
    svc = _users(tmp_path)
    svc.orgs.create_org(name="official", owner_user_id="alice", display_name="Official")
    svc.orgs.upsert_user_profile(
        user_id="Alice",
        display_name="Alice Chen",
        avatar_url="https://example.test/a.png",
    )
    payload = svc.get_public("Alice")
    assert payload["user_id"] == "alice"
    assert payload["display_name"] == "Alice Chen"
    assert payload["avatar_url"] == "https://example.test/a.png"
    assert payload["description"] == ""
    assert payload["official"] is True
    assert payload["official_orgs"] == [
        {"org_id": "official", "display_name": "Official", "official": True}
    ]


def test_unofficial_member_has_no_user_mark(tmp_path: Path) -> None:
    svc = _users(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    svc.orgs.upsert_user_profile(user_id="alice", display_name="Alice")
    payload = svc.get_public("alice")
    assert payload["official"] is False
    assert payload["official_orgs"] == []


def test_public_payload_lists_only_official_orgs(tmp_path: Path) -> None:
    svc = _users(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    svc.orgs.create_org(name="official", owner_user_id="bootstrap", display_name="Official")
    svc.orgs.add_member("official", "alice", role="member")
    payload = svc.get_public("alice")
    assert payload["official"] is True
    assert [row["org_id"] for row in payload["official_orgs"]] == ["official"]


def test_admin_added_never_logged_in_still_200(tmp_path: Path) -> None:
    svc = _users(tmp_path)
    svc.orgs.create_org(name="official", owner_user_id="bootstrap", display_name="Official")
    svc.orgs.add_member("official", "bob", role="member")
    payload = svc.get_public("bob")
    assert payload["user_id"] == "bob"
    assert payload["official"] is True
    assert payload["display_name"] == ""
    assert payload["avatar_url"] == ""
    assert payload["description"] == ""


def test_profile_without_membership_is_not_official(tmp_path: Path) -> None:
    svc = _users(tmp_path)
    svc.orgs.upsert_user_profile(user_id="solo", display_name="Solo")
    payload = svc.get_public("solo")
    assert payload["official"] is False
    assert payload["official_orgs"] == []
    assert payload["display_name"] == "Solo"
    assert payload["maintainer"] is False


def test_maintainer_flag_is_independent_of_official(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGEVAL_REGISTRY_MAINTAINERS", "solo")
    svc = _users(tmp_path)
    svc.orgs.upsert_user_profile(user_id="solo", display_name="Solo")
    payload = svc.get_public("solo")
    assert payload["official"] is False
    assert payload["maintainer"] is True
    svc.orgs.create_org(name="official", owner_user_id="alice", display_name="Official")
    official = svc.get_public("alice")
    assert official["official"] is True
    assert official["maintainer"] is False


def test_unknown_login_is_not_found(tmp_path: Path) -> None:
    svc = _users(tmp_path)
    with pytest.raises(RegistryAppError) as ei:
        svc.get_public("missing")
    assert ei.value.http_status == 404
    assert ei.value.error == "not_found"


def test_self_can_patch_description(tmp_path: Path) -> None:
    from services.registry.store import TokenInfo

    svc = _users(tmp_path)
    svc.orgs.upsert_user_profile(user_id="alice", display_name="Alice")
    payload = svc.patch(
        user_id="Alice",
        description="  hello\nworld  ",
        auth=TokenInfo(scopes=frozenset({"results:read"}), user_id="alice"),
    )
    assert payload["description"] == "hello\nworld"
    assert svc.get_public("alice")["description"] == "hello\nworld"


def test_patch_other_user_is_forbidden(tmp_path: Path) -> None:
    from services.registry.store import TokenInfo

    svc = _users(tmp_path)
    svc.orgs.upsert_user_profile(user_id="alice", display_name="Alice")
    svc.orgs.upsert_user_profile(user_id="bob", display_name="Bob")
    with pytest.raises(RegistryAppError) as ei:
        svc.patch(
            user_id="bob",
            description="nope",
            auth=TokenInfo(scopes=frozenset({"results:read"}), user_id="alice"),
        )
    assert ei.value.http_status == 403
    assert svc.get_public("bob")["description"] == ""


def test_login_upsert_preserves_description(tmp_path: Path) -> None:
    svc = _users(tmp_path)
    svc.orgs.upsert_user_profile(user_id="alice", display_name="Alice")
    svc.orgs.set_user_description("alice", "keeps this")
    stored = svc.orgs.upsert_user_profile(
        user_id="alice",
        display_name="Alice Chen",
        avatar_url="https://example.test/a.png",
        github_id="1",
    )
    assert stored.description == "keeps this"
    payload = svc.get_public("alice")
    assert payload["display_name"] == "Alice Chen"
    assert payload["avatar_url"] == "https://example.test/a.png"
    assert payload["description"] == "keeps this"


def test_empty_user_id_is_invalid(tmp_path: Path) -> None:
    svc = _users(tmp_path)
    with pytest.raises(RegistryAppError) as ei:
        svc.get_public("   ")
    assert ei.value.http_status == 400


def test_get_user_http_is_public(tmp_path: Path) -> None:
    state, _token = build_default_state(
        tmp_path / "reg", bootstrap_token="admin-tok", memory_blob=True
    )
    state.stores.orgs.create_org(name="official", owner_user_id="alice", display_name="Official")
    state.stores.orgs.upsert_user_profile(user_id="alice", display_name="Alice")
    handler = make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/v1/users/Alice")
        resp = conn.getresponse()
        payload = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert resp.status == 200
        assert payload["user_id"] == "alice"
        assert payload["official"] is True

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/v1/users/nobody")
        resp = conn.getresponse()
        missing = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert resp.status == 404
        assert missing["error"] == "not_found"
    finally:
        server.shutdown()
        server.server_close()


def test_patch_user_http_self_only(tmp_path: Path) -> None:
    state, _token = build_default_state(
        tmp_path / "reg", bootstrap_token="admin-tok", memory_blob=True
    )
    state.stores.orgs.upsert_user_profile(user_id="alice", display_name="Alice")
    state.stores.orgs.upsert_user_profile(user_id="bob", display_name="Bob")
    state.tokens.add("alice-tok", DEFAULT_LOGIN_SCOPES, github_user="alice")
    handler = make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    headers = {
        "Authorization": "Bearer alice-tok",
        "Content-Type": "application/json",
    }
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "PATCH",
            "/v1/users/alice",
            body=json.dumps({"description": "Hub bio"}).encode("utf-8"),
            headers=headers,
        )
        resp = conn.getresponse()
        payload = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert resp.status == 200
        assert payload["description"] == "Hub bio"

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "PATCH",
            "/v1/users/bob",
            body=json.dumps({"description": "stolen"}).encode("utf-8"),
            headers=headers,
        )
        resp = conn.getresponse()
        denied = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert resp.status == 403
        assert denied["error"] == "forbidden"

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "PATCH",
            "/v1/users/alice",
            body=json.dumps({"description": "x", "display_name": "nope"}).encode("utf-8"),
            headers=headers,
        )
        resp = conn.getresponse()
        extra = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert resp.status == 400
        assert extra["error"] == "invalid_request"
        assert extra["message"] == "unknown keys"
    finally:
        server.shutdown()
        server.server_close()
