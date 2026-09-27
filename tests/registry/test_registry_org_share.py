"""Org membership, package org binding, result uploaded_by + share (#52/#53/#54)."""

from __future__ import annotations

import json
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from services.registry.app import build_default_state, make_handler
from services.registry.auth.tokens import DEFAULT_LOGIN_SCOPES

from ageval.application.composition import build_publish_command, build_results_commands
from ageval.application.registry_ops.registry_org_command import RegistryOrgCommands
from ageval.registry.client import RegistryClient, RegistryError
from ageval.registry.credentials import write_credentials

publish_dataset = build_publish_command().publish_dataset
_results = build_results_commands()
list_attempt_results = _results.list_attempt_results
upload_attempt_result = _results.upload_attempt_result

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"


@pytest.fixture()
def registry_server(tmp_path: Path):
    data = tmp_path / "reg-data"
    state, token = build_default_state(data, bootstrap_token="boot-token", memory_blob=True)
    handler = make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield {"url": url, "token": token, "state": state}
    server.shutdown()


def _user_token(state, *, user: str, scopes=DEFAULT_LOGIN_SCOPES) -> str:
    raw = f"tok-{user}"
    state.tokens.add(raw, scopes, github_user=user)
    return raw


def test_official_org_reserved_admin_adds_and_removes_member(
    registry_server, tmp_path: Path
) -> None:
    url = registry_server["url"]
    boot = RegistryClient(url, token=registry_server["token"])
    alice = RegistryClient(url, token=_user_token(registry_server["state"], user="alice"))

    with pytest.raises(RegistryError) as ei:
        alice.create_org(name="official", display_name="Official")
    assert ei.value.status == 403

    org = boot.create_org(name="official", display_name="Official", is_claimable=True)
    assert org["org_id"] == "official"
    assert org["is_claimable"] is False

    with pytest.raises(RegistryError) as claim_err:
        alice._request("POST", "/v1/orgs/official/claim")
    assert claim_err.value.status == 403

    cmds = RegistryOrgCommands(
        client_factory=lambda **_kw: RegistryClient(url, token=registry_server["token"])
    )
    added = cmds.add_member(org_id="official", user_id="Alice", role="owner")
    assert added["user_id"] == "alice"
    assert added["role"] == "owner"
    removed = cmds.remove_member(org_id="official", user_id="Alice")
    assert removed["ok"] is True
    assert removed["user_id"] == "alice"


def test_org_create_list_and_publish_requires_org(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = registry_server["url"]
    boot = RegistryClient(url, token=registry_server["token"])
    org = boot.create_org(name="acme", display_name="Acme Lab")
    assert org["org_id"] == "acme"
    listed = boot.list_orgs()
    assert any(i["org_id"] == "acme" for i in listed["items"])

    write_credentials(url=url, token=registry_server["token"], path=tmp_path / "c")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AGEVAL_REGISTRY_URL", url)
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", registry_server["token"])

    with pytest.raises(Exception) as ei:
        publish_dataset(FIXTURE, public=False)
    assert "org" in str(ei.value).lower()

    summary = publish_dataset(FIXTURE, public=False, org="acme")
    assert summary["ok"] is True
    assert summary["org_id"] == "acme"

    meta = boot.get_metadata(dataset_id=summary["dataset_id"], version=summary["version"])
    assert meta.org_id == "acme"


def test_owner_can_patch_org_and_package_display_name(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = registry_server["url"]
    boot = RegistryClient(url, token=registry_server["token"])
    boot.create_org(name="lab", display_name="lab")
    patched = boot.patch_org("lab", display_name="My Lab")
    assert patched["display_name"] == "My Lab"
    assert patched["org_id"] == "lab"
    bio = boot.patch_org("lab", description="A research lab.")
    assert bio["description"] == "A research lab."
    assert bio["display_name"] == "My Lab"

    write_credentials(url=url, token=registry_server["token"], path=tmp_path / "c")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AGEVAL_REGISTRY_URL", url)
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", registry_server["token"])
    from ageval.application.composition import build_plugin_commands

    plugin = REPO / "tests/fixtures/plugins/sample-echo"
    summary = build_plugin_commands().publish_plugin(plugin, public=True, org="lab")
    labeled = boot.patch_package_display_name(summary["package_id"], display_name="Echo probe")
    assert labeled["display_name"] == "Echo probe"
    via_prefix = boot.patch_package_display_name(
        summary["package_id"], display_name="lab/Echo probe"
    )
    assert via_prefix["display_name"] == "Echo probe"
    with pytest.raises(RegistryError):
        boot.patch_package_display_name(summary["package_id"], display_name="other/Echo")


def test_private_package_visible_to_org_member_only(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = registry_server["state"]
    url = registry_server["url"]
    boot = RegistryClient(url, token=registry_server["token"])
    boot.create_org(name="lab")

    alice_tok = _user_token(state, user="alice")
    bob_tok = _user_token(state, user="bob")
    # bootstrap owner adds alice
    boot.add_org_member(org_id="lab", user_id="alice", role="member")

    write_credentials(url=url, token=alice_tok, path=tmp_path / "c")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AGEVAL_REGISTRY_URL", url)
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", alice_tok)
    summary = publish_dataset(FIXTURE, public=False, org="lab")

    alice = RegistryClient(url, token=alice_tok)
    alice.get_metadata(dataset_id=summary["dataset_id"], version=summary["version"])

    bob = RegistryClient(url, token=bob_tok)
    with pytest.raises(RegistryError) as ei:
        bob.get_metadata(dataset_id=summary["dataset_id"], version=summary["version"])
    assert ei.value.status == 404


def test_result_uploaded_by_and_share_org(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = registry_server["state"]
    url = registry_server["url"]
    boot = RegistryClient(url, token=registry_server["token"])
    boot.create_org(name="sharelab")

    alice_tok = _user_token(state, user="alice")
    bob_tok = _user_token(state, user="bob")
    boot.add_org_member(org_id="sharelab", user_id="bob", role="member")

    db = tmp_path / "db"
    shutil.copytree(FIXTURE, db)
    run_id = "sha256_share_run1"
    run_dir = db / ".ageval" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "lock.json").write_text(
        json.dumps(
            {
                "task_id": "hello",
                "dataset_id": "test/publish-min",
                "dataset_version": "0.1.0",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "result.json").write_text(
        json.dumps({"task_id": "hello", "status": "PASS"}),
        encoding="utf-8",
    )

    write_credentials(url=url, token=alice_tok, path=tmp_path / "c")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AGEVAL_REGISTRY_URL", url)
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", alice_tok)

    up = upload_attempt_result(db, run_id=run_id, public=False)
    assert up["ok"] is True
    meta = RegistryClient(url, token=alice_tok).get_attempt(run_id)
    assert meta.get("uploaded_by") == "alice"

    # bob cannot see private unshared result
    with pytest.raises(RegistryError) as ei:
        RegistryClient(url, token=bob_tok).get_attempt(run_id)
    assert ei.value.status == 404

    # alice shares to org; bob is member → can read
    RegistryClient(url, token=alice_tok).share_result(
        result_kind="attempt",
        result_id=run_id,
        target_type="org",
        target_id="sharelab",
    )
    bob_meta = RegistryClient(url, token=bob_tok).get_attempt(run_id)
    assert bob_meta["run_id"] == run_id

    # unshare → bob loses access
    RegistryClient(url, token=alice_tok).unshare_result(
        result_kind="attempt",
        result_id=run_id,
        target_type="org",
        target_id="sharelab",
    )
    with pytest.raises(RegistryError) as ei2:
        RegistryClient(url, token=bob_tok).get_attempt(run_id)
    assert ei2.value.status == 404

    # non-owner cannot share
    with pytest.raises(RegistryError):
        RegistryClient(url, token=bob_tok).share_result(
            result_kind="attempt",
            result_id=run_id,
            target_type="user",
            target_id="bob",
        )

    # list does not leak to bob
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", bob_tok)
    listed = list_attempt_results(dataset_id="test/publish-min")
    assert listed["count"] == 0


def test_org_invite_key_create_join_and_limits(registry_server) -> None:
    """Owner creates invite key; user joins; max_uses exhausts; revoke blocks."""
    state = registry_server["state"]
    url = registry_server["url"]
    boot = RegistryClient(url, token=registry_server["token"])
    boot.create_org(name="invitelab", display_name="Invite Lab")

    # Create invite: max 1 use, long expiry
    st, raw, _ = boot._request(
        "POST",
        "/v1/orgs/invitelab/invite-keys",
        body=json.dumps({"max_uses": 1, "expires_in_days": 3}).encode(),
        headers=boot._headers(content_type="application/json", auth=True),
    )
    assert st == 201, raw
    created = json.loads(raw.decode())
    assert created.get("invite_key", "").startswith("ageval-inv_")
    assert created["max_uses"] == 1
    key = created["invite_key"]
    # List never re-materializes the secret; only prefix metadata.
    st_list, raw_list, _ = boot._request(
        "GET",
        "/v1/orgs/invitelab/invite-keys",
        headers=boot._headers(auth=True),
    )
    assert st_list == 200
    listed = json.loads(raw_list.decode())
    items = listed.get("items") or []
    match = next((i for i in items if i.get("key_id") == created["key_id"]), None)
    assert match is not None, listed
    assert "invite_key" not in match
    assert match.get("token_prefix", "").startswith("ageval-inv_")

    carol = _user_token(state, user="carol")
    carol_cli = RegistryClient(url, token=carol)
    st2, raw2, _ = carol_cli._request(
        "POST",
        "/v1/orgs/join",
        body=json.dumps({"invite_key": key}).encode(),
        headers=carol_cli._headers(content_type="application/json", auth=True),
    )
    assert st2 == 200, raw2
    joined = json.loads(raw2.decode())
    assert joined["org_id"] == "invitelab"
    assert joined["role"] == "member"

    # Exhausted for second user
    dave = _user_token(state, user="dave")
    dave_cli = RegistryClient(url, token=dave)
    with pytest.raises(RegistryError) as ei:
        dave_cli._request(
            "POST",
            "/v1/orgs/join",
            body=json.dumps({"invite_key": key}).encode(),
            headers=dave_cli._headers(content_type="application/json", auth=True),
        )
    assert ei.value.status == 403
    assert "exhaust" in ei.value.message.lower()

    # New key then revoke
    st4, raw4, _ = boot._request(
        "POST",
        "/v1/orgs/invitelab/invite-keys",
        body=json.dumps({"max_uses": 5}).encode(),
        headers=boot._headers(content_type="application/json", auth=True),
    )
    assert st4 == 201
    k2 = json.loads(raw4.decode())
    kid = k2["key_id"]
    st5, _, _ = boot._request(
        "DELETE",
        f"/v1/orgs/invitelab/invite-keys/{kid}",
        headers=boot._headers(auth=True),
    )
    assert st5 == 200
    with pytest.raises(RegistryError) as ei2:
        dave_cli._request(
            "POST",
            "/v1/orgs/join",
            body=json.dumps({"invite_key": k2["invite_key"]}).encode(),
            headers=dave_cli._headers(content_type="application/json", auth=True),
        )
    assert ei2.value.status == 403
    assert "revok" in ei2.value.message.lower()


def test_org_leave_and_dissolve(registry_server) -> None:
    state = registry_server["state"]
    url = registry_server["url"]
    boot = RegistryClient(url, token=registry_server["token"])
    boot.create_org(name="doomed", display_name="Doomed Lab")

    # Add member eve; she can leave
    eve = _user_token(state, user="eve")
    st, raw, _ = boot._request(
        "POST",
        "/v1/orgs/doomed/members",
        body=json.dumps({"user_id": "eve", "role": "member"}).encode(),
        headers=boot._headers(content_type="application/json", auth=True),
    )
    assert st == 201, raw
    eve_cli = RegistryClient(url, token=eve)
    st2, raw2, _ = eve_cli._request(
        "POST",
        "/v1/orgs/doomed/leave",
        body=b"{}",
        headers=eve_cli._headers(content_type="application/json", auth=True),
    )
    assert st2 == 200, raw2

    # Sole owner cannot leave
    with pytest.raises(RegistryError) as ei:
        boot._request(
            "POST",
            "/v1/orgs/doomed/leave",
            body=b"{}",
            headers=boot._headers(content_type="application/json", auth=True),
        )
    assert ei.value.status == 403

    # Dissolve works when no packages
    st3, raw3, _ = boot._request(
        "DELETE",
        "/v1/orgs/doomed",
        headers=boot._headers(auth=True),
    )
    assert st3 == 200, raw3
    listed = boot.list_orgs()
    assert all(i["org_id"] != "doomed" for i in listed.get("items") or [])


def test_org_set_role_and_transfer_http(registry_server) -> None:
    state = registry_server["state"]
    url = registry_server["url"]
    boot = RegistryClient(url, token=registry_server["token"])
    boot.create_org(name="handoff", display_name="Handoff Lab")
    boot.add_org_member(org_id="handoff", user_id="alice", role="member")
    alice = RegistryClient(url, token=_user_token(state, user="alice"))

    st, raw, _ = boot._request(
        "PATCH",
        "/v1/orgs/handoff/members/alice",
        body=json.dumps({"role": "owner"}).encode(),
        headers=boot._headers(content_type="application/json", auth=True),
    )
    assert st == 200, raw
    body = json.loads(raw.decode())
    assert body["role"] == "owner"

    # Last remaining owner after bootstrap also owns; remove bootstrap? skip.
    # Sole-owner delete is 403: create a one-owner org via alice.
    alice.create_org(name="solo", display_name="Solo")
    with pytest.raises(RegistryError) as last:
        alice._request(
            "DELETE",
            "/v1/orgs/solo/members/alice",
            headers=alice._headers(auth=True),
        )
    assert last.value.status == 403

    st2, raw2, _ = boot._request(
        "POST",
        "/v1/orgs/handoff/transfer",
        body=json.dumps({"user_id": "alice"}).encode(),
        headers=boot._headers(content_type="application/json", auth=True),
    )
    assert st2 == 200, raw2
    xfer = json.loads(raw2.decode())
    assert xfer["from"]["user_id"] == "bootstrap"
    assert xfer["from"]["role"] == "member"
    assert xfer["to"]["user_id"] == "alice"
    assert xfer["to"]["role"] == "owner"

    with pytest.raises(RegistryError) as non_member:
        alice._request(
            "POST",
            "/v1/orgs/handoff/transfer",
            body=json.dumps({"user_id": "carol"}).encode(),
            headers=alice._headers(content_type="application/json", auth=True),
        )
    assert non_member.value.status == 404


def test_org_set_role_and_transfer_commands(registry_server) -> None:
    url = registry_server["url"]
    boot = RegistryClient(url, token=registry_server["token"])
    boot.create_org(name="lab", display_name="Lab")
    cmds = RegistryOrgCommands(client_factory=lambda **_kw: boot)
    added = cmds.add_member(org_id="lab", user_id="Dana", role="member")
    assert added["role"] == "member"
    promoted = cmds.set_member_role(org_id="lab", user_id="Dana", role="owner")
    assert promoted["ok"] is True
    assert promoted["user_id"] == "dana"
    assert promoted["role"] == "owner"
    handed = cmds.transfer(org_id="lab", user_id="dana")
    assert handed["ok"] is True
    assert handed["from"]["user_id"] == "bootstrap"
    assert handed["from"]["role"] == "member"
    assert handed["to"]["user_id"] == "dana"
    assert handed["to"]["role"] == "owner"
