"""Owner delete / set-visibility / unshare / replace."""

from __future__ import annotations

import json
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from services.registry.app import build_default_state, make_handler
from services.registry.auth.tokens import DEFAULT_LOGIN_SCOPES

from ageval.application.composition import (
    build_publish_command,
    build_registry_list_commands,
    build_results_commands,
)
from ageval.config.errors import ConfigError
from ageval.registry.client import RegistryClient, RegistryError
from ageval.registry.credentials import write_credentials

publish_dataset = build_publish_command().publish_dataset
_list = build_registry_list_commands()
delete_package_release = _list.delete_package_release
set_package_visibility = _list.set_package_visibility
_results = build_results_commands()
delete_result = _results.delete_result
set_result_visibility = _results.set_result_visibility
share_result = _results.share_result
unshare_result = _results.unshare_result
upload_attempt_result = _results.upload_attempt_result
upload_suite_result = _results.upload_suite_result

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


def _env_as(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    url: str,
    token: str,
) -> None:
    write_credentials(url=url, token=token, path=tmp_path / "c")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AGEVAL_REGISTRY_URL", url)
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", token)


def _seed_attempt(
    tmp_path: Path,
    *,
    run_id: str = "sha256_owner_run1",
    suite_run_id: str | None = None,
) -> Path:
    db = tmp_path / "db"
    if not db.exists():
        shutil.copytree(FIXTURE, db)
    run_dir = db / ".ageval" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
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
    return db


def _seed_suite(tmp_path: Path, *, suite_run_id: str, attempt_run_id: str) -> Path:
    db = _seed_attempt(tmp_path, run_id=attempt_run_id, suite_run_id=suite_run_id)
    suite_dir = db / ".ageval" / "suite-runs" / suite_run_id
    suite_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "suite_run_id": suite_run_id,
        "dataset_id": "test/publish-min",
        "dataset_version": "0.1.0",
        "pass_rate": 1.0,
        "mean_score": 1.0,
        "metrics": {"pass_rate": 1.0, "mean_score": 1.0},
        "task_refs": [
            {
                "task_id": "hello",
                "run_id": attempt_run_id,
                "attempt_run_ids": [attempt_run_id],
            }
        ],
        "exit_code": 0,
    }
    (suite_dir / "summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )
    return db


# ---------------------------------------------------------------------------
# B — results delete + set-visibility + cascade
# ---------------------------------------------------------------------------


def test_attempt_delete_and_visibility_owner_only(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = registry_server["state"]
    url = registry_server["url"]
    alice_tok = _user_token(state, user="alice")
    bob_tok = _user_token(state, user="bob")
    _env_as(monkeypatch, tmp_path, url=url, token=alice_tok)

    db = _seed_attempt(tmp_path)
    run_id = "sha256_owner_run1"
    up = upload_attempt_result(db, run_id=run_id, public=False)
    assert up["ok"] is True

    # set visibility private → public
    vis = set_result_visibility(result_kind="attempt", result_id=run_id, visibility="public")
    assert vis["visibility"] == "public"
    bob = RegistryClient(url, token=bob_tok)
    assert bob.get_attempt(run_id)["visibility"] == "public"

    # flip back private; bob loses sight
    set_result_visibility(result_kind="attempt", result_id=run_id, visibility="private")
    with pytest.raises(RegistryError) as ei:
        bob.get_attempt(run_id)
    assert ei.value.status == 404

    # non-owner cannot delete
    with pytest.raises(ConfigError):
        monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", bob_tok)
        delete_result(result_kind="attempt", result_id=run_id)

    # owner deletes
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", alice_tok)
    deleted = delete_result(result_kind="attempt", result_id=run_id)
    assert deleted["ok"] is True
    assert deleted["result_id"] == run_id

    with pytest.raises(RegistryError) as ei2:
        RegistryClient(url, token=alice_tok).get_attempt(run_id)
    assert ei2.value.status == 404


def test_suite_delete_default_no_cascade_and_with_attempts(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = registry_server["state"]
    url = registry_server["url"]
    alice_tok = _user_token(state, user="alice")
    _env_as(monkeypatch, tmp_path, url=url, token=alice_tok)

    suite_id = "suite_owner_1"
    att_id = "sha256_suite_att1"
    db = _seed_suite(tmp_path, suite_run_id=suite_id, attempt_run_id=att_id)

    upload_attempt_result(db, run_id=att_id, public=False, suite_run_id=suite_id)
    upload_suite_result(db, suite_run_id=suite_id, public=False)

    # default: suite delete keeps attempts
    out = delete_result(result_kind="suite", result_id=suite_id, with_attempts=False)
    assert out["ok"] is True
    assert out.get("deleted_attempts") == []
    RegistryClient(url, token=alice_tok).get_attempt(att_id)

    # re-upload suite, then cascade
    upload_suite_result(db, suite_run_id=suite_id, public=False)
    casc = delete_result(result_kind="suite", result_id=suite_id, with_attempts=True)
    assert casc["ok"] is True
    assert att_id in casc.get("deleted_attempts", [])
    with pytest.raises(RegistryError):
        RegistryClient(url, token=alice_tok).get_attempt(att_id)
    with pytest.raises(RegistryError):
        RegistryClient(url, token=alice_tok).get_suite(suite_id)


# ---------------------------------------------------------------------------
# C — unshare CLI/application
# ---------------------------------------------------------------------------


def test_unshare_application_and_non_owner_denied(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = registry_server["state"]
    url = registry_server["url"]
    boot = RegistryClient(url, token=registry_server["token"])
    boot.create_org(name="sharelab2")
    alice_tok = _user_token(state, user="alice")
    bob_tok = _user_token(state, user="bob")
    boot.add_org_member(org_id="sharelab2", user_id="bob", role="member")
    _env_as(monkeypatch, tmp_path, url=url, token=alice_tok)

    db = _seed_attempt(tmp_path)
    run_id = "sha256_owner_run1"
    upload_attempt_result(db, run_id=run_id, public=False)
    share_result(
        result_kind="attempt",
        result_id=run_id,
        share_orgs=["sharelab2"],
    )
    assert RegistryClient(url, token=bob_tok).get_attempt(run_id)["run_id"] == run_id

    unshare_result(
        result_kind="attempt",
        result_id=run_id,
        share_orgs=["sharelab2"],
    )
    with pytest.raises(RegistryError) as ei:
        RegistryClient(url, token=bob_tok).get_attempt(run_id)
    assert ei.value.status == 404

    # non-owner cannot unshare (even if no share remains, manage denied → 404)
    with pytest.raises(ConfigError):
        monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", bob_tok)
        unshare_result(
            result_kind="attempt",
            result_id=run_id,
            share_users=["bob"],
        )


# ---------------------------------------------------------------------------
# A — package delete + set-visibility
# ---------------------------------------------------------------------------


def test_package_delete_and_visibility_org_owner_only(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = registry_server["state"]
    url = registry_server["url"]
    boot = RegistryClient(url, token=registry_server["token"])
    boot.create_org(name="ownlab")
    alice_tok = _user_token(state, user="alice")
    bob_tok = _user_token(state, user="bob")
    # bootstrap is org owner; add alice as member only
    boot.add_org_member(org_id="ownlab", user_id="alice", role="member")
    boot.add_org_member(org_id="ownlab", user_id="bob", role="member")

    _env_as(monkeypatch, tmp_path, url=url, token=registry_server["token"])
    pub = publish_dataset(FIXTURE, public=False, org="ownlab")
    ref = f"{pub['dataset_id']}@{pub['version']}"

    # owner (bootstrap) can set visibility
    flipped = set_package_visibility(ref, visibility="public")
    assert flipped["visibility"] == "public"
    bob = RegistryClient(url, token=bob_tok)
    assert bob.get_metadata(dataset_id=pub["dataset_id"], version=pub["version"]).visibility == (
        "public"
    )

    set_package_visibility(ref, visibility="private")

    # member cannot delete
    with pytest.raises(ConfigError):
        monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", alice_tok)
        delete_package_release(ref)

    # owner deletes
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", registry_server["token"])
    deleted = delete_package_release(ref)
    assert deleted["ok"] is True
    with pytest.raises(RegistryError) as ei:
        boot.get_metadata(dataset_id=pub["dataset_id"], version=pub["version"])
    assert ei.value.status == 404


# ---------------------------------------------------------------------------
# D — replace / conflict policy
# ---------------------------------------------------------------------------


def test_attempt_replace_requires_flag_and_owner(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = registry_server["state"]
    url = registry_server["url"]
    alice_tok = _user_token(state, user="alice")
    bob_tok = _user_token(state, user="bob")
    _env_as(monkeypatch, tmp_path, url=url, token=alice_tok)

    db = _seed_attempt(tmp_path)
    run_id = "sha256_owner_run1"
    first = upload_attempt_result(db, run_id=run_id, public=False)
    assert first["ok"] is True

    # default: conflict
    with pytest.raises(ConfigError) as ei:
        upload_attempt_result(db, run_id=run_id, public=False)
    assert "already exists" in str(ei.value).lower() or "conflict" in str(ei.value).lower()

    # non-owner replace → fail-closed
    (db / ".ageval" / "runs" / run_id / "result.json").write_text(
        json.dumps({"task_id": "hello", "status": "FAIL"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", bob_tok)
    with pytest.raises(ConfigError):
        upload_attempt_result(db, run_id=run_id, public=False, replace=True)

    # owner replace succeeds and rewrites blob/meta
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", alice_tok)
    replaced = upload_attempt_result(db, run_id=run_id, public=True, replace=True)
    assert replaced["ok"] is True
    assert replaced.get("replaced") is True
    assert replaced["visibility"] == "public"
    meta = RegistryClient(url, token=alice_tok).get_attempt(run_id)
    assert meta["visibility"] == "public"
    assert meta["status"] == "FAIL"
    # digest may or may not change depending on archive contents; status field is authority


def test_package_replace_conflict_and_owner(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = registry_server["url"]
    boot = RegistryClient(url, token=registry_server["token"])
    boot.create_org(name="replacelab")
    _env_as(monkeypatch, tmp_path, url=url, token=registry_server["token"])

    first = publish_dataset(FIXTURE, public=False, org="replacelab")
    assert first["ok"] is True

    with pytest.raises(ConfigError) as ei:
        publish_dataset(FIXTURE, public=False, org="replacelab")
    assert "already exists" in str(ei.value).lower() or "conflict" in str(ei.value).lower()

    again = publish_dataset(FIXTURE, public=True, org="replacelab", replace=True)
    assert again["ok"] is True
    assert again.get("replaced") is True
    assert again["visibility"] == "public"
    meta = boot.get_metadata(dataset_id=first["dataset_id"], version=first["version"])
    assert meta.visibility == "public"
