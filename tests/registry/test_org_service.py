"""OrgService owns member visibility (not a Handler parallel if)."""

from __future__ import annotations

from pathlib import Path

import pytest
from services.registry.access import AccessPolicy
from services.registry.errors import RegistryAppError
from services.registry.org_service import OrgService
from services.registry.store import TokenInfo
from services.registry.store_schema import (
    open_sqlite_stores,
)


def _orgs(tmp_path: Path) -> OrgService:
    meta = open_sqlite_stores(tmp_path / "meta.sqlite3")
    return OrgService(
        meta.orgs, AccessPolicy(orgs=meta.orgs, packages=meta.packages, results=meta.results)
    )


def test_list_members_hides_org_from_outsiders(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    outsider = TokenInfo(scopes=frozenset({"results:read"}), user_id="bob")
    with pytest.raises(RegistryAppError) as ei:
        svc.list_members(org_id="acme", auth=outsider)
    assert ei.value.http_status == 404
    assert ei.value.error == "not_found"


def test_regular_org_is_not_official(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    payload = svc.create(
        name="acme",
        display_name="Acme",
        is_claimable=False,
        auth=_user(),
    )
    assert payload["official"] is False
    assert payload["description"] == ""


def test_create_and_patch_org_description(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    created = svc.create(
        name="acme",
        display_name="Acme",
        description="Lab notes.",
        is_claimable=False,
        auth=_user(),
    )
    assert created["description"] == "Lab notes."
    patched = svc.patch(
        org_id="acme",
        description="Updated bio",
        auth=_user(),
    )
    assert patched["description"] == "Updated bio"
    assert patched["display_name"] == "Acme"
    named = svc.patch(org_id="acme", display_name="Acme Lab", auth=_user())
    assert named["display_name"] == "Acme Lab"
    assert named["description"] == "Updated bio"


def test_patch_org_icon_key_and_github(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    svc.create(
        name="acme",
        display_name="Acme",
        is_claimable=False,
        auth=_user(),
    )
    keyed = svc.patch(org_id="acme", icon_key="openai", auth=_user())
    assert keyed["icon_key"] == "openai"
    assert "icon_github" not in keyed
    linked = svc.patch(
        org_id="acme",
        icon_github="https://github.com/octocat",
        auth=_user(),
    )
    assert linked["icon_github"] == "octocat"
    assert linked["icon_key"] == "openai"
    cleared = svc.patch(org_id="acme", icon_key="", icon_github="", auth=_user())
    assert "icon_key" not in cleared
    assert "icon_github" not in cleared
    with pytest.raises(RegistryAppError) as ei:
        svc.patch(org_id="acme", icon_key="not-a-brand", auth=_user())
    assert ei.value.error == "invalid_request"


def test_list_members_visible_to_member(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    owner = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    payload = svc.list_members(org_id="acme", auth=owner)
    assert payload["org_id"] == "acme"
    assert any(item["user_id"] == "alice" for item in payload["items"])


def test_list_members_puts_owners_first(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="zack", display_name="Acme")
    svc.orgs.add_member("acme", "amy", role="member")
    svc.orgs.add_member("acme", "bob", role="owner")
    owner = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="zack")
    payload = svc.list_members(org_id="acme", auth=owner)
    ids = [item["user_id"] for item in payload["items"]]
    roles = [item["role"] for item in payload["items"]]
    assert roles[:2] == ["owner", "owner"]
    assert ids[:2] == ["bob", "zack"]
    assert ids[2:] == ["amy"]


def _user(*, admin: bool = False, user_id: str = "alice") -> TokenInfo:
    scopes = frozenset({"admin"}) if admin else frozenset({"registry:publish"})
    return TokenInfo(scopes=scopes, user_id=user_id)


def test_non_admin_cannot_create_official_org(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    with pytest.raises(RegistryAppError) as ei:
        svc.create(name="official", display_name="Official", is_claimable=False, auth=_user())
    assert ei.value.http_status == 403
    assert ei.value.error == "forbidden"


def test_admin_creates_official_org_not_claimable(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    payload = svc.create(
        name="Official",
        display_name="Official",
        is_claimable=True,
        auth=_user(admin=True, user_id="bootstrap"),
    )
    assert payload["org_id"] == "official"
    assert payload["is_claimable"] is False
    assert payload["official"] is True


def test_official_org_cannot_be_claimed(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    svc.orgs.create_org(
        name="official",
        owner_user_id="bootstrap",
        display_name="Official",
        is_claimable=True,
    )
    with pytest.raises(RegistryAppError) as ei:
        svc.claim(org_id="official", auth=_user())
    assert ei.value.http_status == 403
    assert "cannot claim" in ei.value.message


def test_promote_existing_member_without_readd(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    svc.orgs.add_member("acme", "bob", role="member")
    owner = _user()
    promoted = svc.set_member_role(org_id="acme", user_id="Bob", role="owner", auth=owner)
    assert promoted["user_id"] == "bob"
    assert promoted["role"] == "owner"
    mem = svc.orgs.membership("acme", "bob")
    assert mem is not None and mem.role == "owner"


def test_last_owner_cannot_be_demoted_removed_or_transfer_to_non_member(
    tmp_path: Path,
) -> None:
    svc = _orgs(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    owner = _user()
    with pytest.raises(RegistryAppError) as demote:
        svc.set_member_role(org_id="acme", user_id="alice", role="member", auth=owner)
    assert demote.value.http_status == 403
    with pytest.raises(RegistryAppError) as removed:
        svc.remove_member(org_id="acme", user_id="alice", auth=owner)
    assert removed.value.http_status == 403
    with pytest.raises(RegistryAppError) as missing:
        svc.transfer(org_id="acme", user_id="carol", auth=owner)
    assert missing.value.http_status == 404
    assert svc.orgs.membership("acme", "alice") is not None
    assert svc.orgs.membership("acme", "alice").role == "owner"  # type: ignore[union-attr]


def test_transfer_is_atomic_and_demotes_caller(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    svc.orgs.add_member("acme", "bob", role="member")
    payload = svc.transfer(org_id="acme", user_id="bob", auth=_user())
    assert payload["ok"] is True
    assert payload["from"]["user_id"] == "alice"
    assert payload["from"]["role"] == "member"
    assert payload["to"]["user_id"] == "bob"
    assert payload["to"]["role"] == "owner"
    assert svc.orgs.membership("acme", "alice").role == "member"  # type: ignore[union-attr]
    assert svc.orgs.membership("acme", "bob").role == "owner"  # type: ignore[union-attr]


def test_transfer_when_target_already_owner_only_demotes_caller(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    svc.orgs.add_member("acme", "bob", role="owner")
    payload = svc.transfer(org_id="acme", user_id="bob", auth=_user())
    assert payload["to"]["role"] == "owner"
    assert payload["from"]["role"] == "member"
    assert svc.orgs.count_org_owners("acme") == 1


def test_member_cannot_set_role_or_transfer(tmp_path: Path) -> None:
    svc = _orgs(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    svc.orgs.add_member("acme", "bob", role="member")
    member = _user(user_id="bob")
    with pytest.raises(RegistryAppError) as role_err:
        svc.set_member_role(org_id="acme", user_id="bob", role="owner", auth=member)
    assert role_err.value.http_status == 403
    with pytest.raises(RegistryAppError) as xfer_err:
        svc.transfer(org_id="acme", user_id="alice", auth=member)
    assert xfer_err.value.http_status == 403
