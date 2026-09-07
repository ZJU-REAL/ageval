"""Inbox requests for Public board listing and Agent Performance."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from services.registry.access import AccessPolicy
from services.registry.errors import RegistryAppError
from services.registry.package_service import PackageService
from services.registry.request_service import RequestService
from services.registry.result_service import ResultService
from services.registry.runtime_service import RuntimeService
from services.registry.store import MemoryBlobStore, TokenInfo
from services.registry.store_schema import (
    open_sqlite_stores,
)

from ageval.registry.agent_package import (
    AGENT_MEDIA_TYPE,
    build_agent_archive,
    compute_agent_digest,
)
from ageval.registry.archive import MEDIA_TYPE, build_archive
from ageval.registry.digest import compute_package_digest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"
AGENT = REPO / "examples" / "agents" / "pi-default"
PI = {
    "executor": "acp",
    "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
    "model": "entry-default",
}


def _svcs(tmp_path: Path) -> tuple[PackageService, ResultService, RequestService, RuntimeService]:
    meta = open_sqlite_stores(tmp_path / "meta.sqlite3")
    blobs = MemoryBlobStore()
    access = AccessPolicy(orgs=meta.orgs, packages=meta.packages, results=meta.results)
    packages = PackageService(meta.packages, meta.orgs, blobs, access, max_upload=64 * 1024 * 1024)
    results = ResultService(
        meta.results,
        meta.packages,
        meta.orgs,
        meta.inbox,
        blobs,
        access,
        max_upload=64 * 1024 * 1024,
    )
    requests = RequestService(meta.inbox, meta.orgs, meta.packages, meta.results, access, results)
    return packages, results, requests, RuntimeService(meta.inbox, meta.packages, results)


def _as_path(tmp_path: Path, data: bytes, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _publish_dataset(
    packages: PackageService,
    tmp_path: Path,
    *,
    dataset_id: str,
    org_id: str,
    owner: str,
) -> None:
    if packages.orgs.get_org(org_id) is None:
        packages.orgs.create_org(name=org_id, owner_user_id=owner, display_name=org_id)
    archive, blob_digest, size = build_archive(FIXTURE)
    packages.publish(
        meta={
            "dataset_id": dataset_id,
            "version": "0.1.0",
            "package_digest": compute_package_digest(FIXTURE),
            "blob_digest": blob_digest,
            "media_type": MEDIA_TYPE,
            "visibility": "public",
            "org_id": org_id,
            "size": size,
            "package_kind": "dataset",
        },
        archive=_as_path(tmp_path, archive, f"{dataset_id.replace('/', '_')}.tar.gz"),
        auth=TokenInfo(scopes=frozenset({"registry:publish"}), user_id=owner),
    )


def _publish_agent(
    packages: PackageService,
    tmp_path: Path,
    *,
    package_id: str,
    org_id: str,
    owner: str,
) -> None:
    if packages.orgs.get_org(org_id) is None:
        packages.orgs.create_org(name=org_id, owner_user_id=owner, display_name=org_id)
    archive, blob_digest, size = build_agent_archive(AGENT)
    packages.publish(
        meta={
            "dataset_id": package_id,
            "version": "0.1.0",
            "package_digest": compute_agent_digest(AGENT),
            "blob_digest": blob_digest,
            "media_type": AGENT_MEDIA_TYPE,
            "visibility": "public",
            "org_id": org_id,
            "size": size,
            "package_kind": "agent",
        },
        archive=_as_path(tmp_path, archive, f"{package_id.replace('/', '_')}.tar.gz"),
        auth=TokenInfo(scopes=frozenset({"registry:publish"}), user_id=owner),
    )


def _upload(
    results: ResultService,
    tmp_path: Path,
    *,
    suite_run_id: str,
    dataset_id: str,
    user_id: str,
    agent_profiles: dict[str, dict[str, object]] | None = None,
    task_refs: list[dict[str, object]] | None = None,
    visibility: str = "public",
    replace: bool = False,
) -> dict[str, object]:
    archive = suite_run_id.encode()
    blob = f"sha256:{hashlib.sha256(archive).hexdigest()}"
    meta: dict[str, object] = {
        "suite_run_id": suite_run_id,
        "dataset_id": dataset_id,
        "dataset_version": "0.1.0",
        "visibility": visibility,
        "blob_digest": blob,
        "size": len(archive),
        "pass_rate": 0.4,
        "mean_score": 0.4,
        "metrics": {"pass_rate": 0.4, "n_attempts": 1},
        "task_refs": task_refs
        if task_refs is not None
        else [{"task_id": "hello", "status": "PASS", "score": 1.0}],
        "config_fingerprint": "sha256:aaaaaaaa",
    }
    if agent_profiles is not None:
        meta["job_overlay"] = {"agent_profiles": agent_profiles}
    if replace:
        meta["replace"] = True
    return results.upload_suite(
        meta=meta,
        archive=_as_path(tmp_path, archive, f"{suite_run_id}.bin"),
        auth=TokenInfo(scopes=frozenset({"results:upload"}), user_id=user_id),
    )


def test_listing_requires_dataset_org_approve(tmp_path: Path) -> None:
    packages, results, requests, _rt = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    _publish_dataset(packages, tmp_path, dataset_id="acme/bench", org_id="acme", owner="bob")
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    _upload(results, tmp_path, suite_run_id="s_off", dataset_id="official/gaia", user_id="bob")
    _upload(results, tmp_path, suite_run_id="s_acme", dataset_id="acme/bench", user_id="bob")
    board = results.list_suites(auth=alice, dataset_id="official/gaia", board=True)
    assert board["items"] == []
    listing = requests.apply(kind="leaderboard_list", suite_run_id="s_off", auth=bob)
    assert listing["status"] == "pending"
    assert listing["owner_org_id"] == "official"
    with pytest.raises(RegistryAppError) as forbidden:
        requests.decide(request_ids=[listing["request_id"]], action="approve", auth=bob)
    assert forbidden.value.http_status == 404
    inbox = requests.inbox(auth=alice)
    assert [i["request_id"] for i in inbox["items"]] == [listing["request_id"]]
    assert requests.inbox(auth=bob)["items"] == []
    requests.decide(request_ids=[listing["request_id"]], action="approve", auth=alice)
    history = requests.inbox(auth=alice)["items"]
    assert any(
        i["request_id"] == listing["request_id"] and i["status"] == "approved" for i in history
    )
    board = results.list_suites(auth=alice, dataset_id="official/gaia", board=True)
    assert [i["suite_run_id"] for i in board["items"]] == ["s_off"]
    acme = requests.apply(kind="leaderboard_list", suite_run_id="s_acme", auth=bob)
    requests.decide(request_ids=[acme["request_id"]], action="approve", auth=bob)
    acme_board = results.list_suites(auth=bob, dataset_id="acme/bench", board=True)
    assert [i["suite_run_id"] for i in acme_board["items"]] == ["s_acme"]


def test_listing_reject_and_incomplete_fail_closed(tmp_path: Path) -> None:
    packages, results, requests, _rt = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    _upload(results, tmp_path, suite_run_id="s_ok", dataset_id="official/gaia", user_id="bob")
    _upload(
        results,
        tmp_path,
        suite_run_id="s_miss",
        dataset_id="official/gaia",
        user_id="bob",
        task_refs=[],
    )
    with pytest.raises(RegistryAppError, match="complete release-bound"):
        requests.apply(kind="leaderboard_list", suite_run_id="s_miss", auth=bob)
    row = requests.apply(kind="leaderboard_list", suite_run_id="s_ok", auth=bob)
    requests.decide(request_ids=[row["request_id"]], action="reject", auth=alice)
    board = results.list_suites(auth=alice, dataset_id="official/gaia", board=True)
    assert board["items"] == []
    meta = results.serve_suite_meta(suite_run_id="s_ok", auth=bob)
    assert meta["board_listed"] is False
    assert meta["config_fingerprint"] == "sha256:aaaaaaaa"


def test_apply_builtin_performance_is_request(tmp_path: Path) -> None:
    packages, results, requests, runtimes = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    _upload(
        results,
        tmp_path,
        suite_run_id="s_builtin",
        dataset_id="official/gaia",
        user_id="bob",
        agent_profiles={"solver": dict(PI)},
    )
    applied = requests.apply(
        kind="agent_performance",
        suite_run_id="s_builtin",
        auth=bob,
        agent="pi",
    )
    assert applied["status"] == "pending"
    assert applied["owner_org_id"] == "_maintainers"
    assert applied.get("direct_attach") is not True
    meta = results.serve_suite_meta(suite_run_id="s_builtin", auth=bob)
    assert "agent_ref" not in meta["job_overlay"]["agent_profiles"]["solver"]
    assert requests.inbox(auth=alice)["items"] == []
    rows = runtimes.performances_for_agent("pi", alice)
    assert [r["suite_run_id"] for r in rows] == ["s_builtin"]
    http = {
        "executor": "openai-http",
        "extensions": [{"plugin": "openai-http"}, {"plugin": "local"}],
        "model": "m",
    }
    _upload(
        results,
        tmp_path,
        suite_run_id="s_roles",
        dataset_id="official/gaia",
        user_id="bob",
        agent_profiles={"user": dict(http), "service": dict(http)},
    )
    pending_role = requests.apply(
        kind="agent_performance",
        suite_run_id="s_roles",
        auth=bob,
        agent="service=openai-http",
    )
    assert pending_role["status"] == "pending"
    assert pending_role["agent_ref"].startswith("service=")


def test_maintainer_direct_attaches_builtin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGEVAL_REGISTRY_MAINTAINERS", "alice")
    packages, results, requests, runtimes = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    _upload(
        results,
        tmp_path,
        suite_run_id="s_builtin",
        dataset_id="official/gaia",
        user_id="bob",
        agent_profiles={"solver": dict(PI)},
    )
    pending = requests.apply(
        kind="agent_performance",
        suite_run_id="s_builtin",
        auth=bob,
        agent="pi",
    )
    assert pending["status"] == "pending"
    assert [i["request_id"] for i in requests.inbox(auth=alice)["items"]] == [pending["request_id"]]
    requests.decide(
        request_ids=[pending["request_id"]],
        action="approve",
        auth=alice,
        canonical_model="alibaba/qwen-max",
    )
    meta = results.serve_suite_meta(suite_run_id="s_builtin", auth=bob)
    assert str(meta["job_overlay"]["agent_profiles"]["solver"]["agent_ref"]).startswith("pi@0.1.0+")
    _upload(
        results,
        tmp_path,
        suite_run_id="s_alice",
        dataset_id="official/gaia",
        user_id="alice",
        agent_profiles={"solver": dict(PI)},
    )
    attached = requests.apply(
        kind="agent_performance",
        suite_run_id="s_alice",
        auth=alice,
        agent="pi",
    )
    assert attached.get("direct_attach") is True


def test_performance_request_approve_uses_attach(tmp_path: Path) -> None:
    packages, results, requests, runtimes = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    _publish_agent(
        packages, tmp_path, package_id="official/pi-default", org_id="official", owner="alice"
    )
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    uploaded = _upload(
        results,
        tmp_path,
        suite_run_id="s_bob",
        dataset_id="official/gaia",
        user_id="bob",
        agent_profiles={"solver": dict(PI)},
    )
    fingerprint = uploaded["config_fingerprint"]
    applied = requests.apply(
        kind="agent_performance",
        suite_run_id="s_bob",
        auth=bob,
        agent="official/pi-default@0.1.0",
    )
    assert applied["status"] == "pending"
    assert applied["owner_org_id"] == "official"
    assert runtimes.performances_for_agent("official/pi-default", alice) == []
    requests.decide(
        request_ids=[applied["request_id"]],
        action="approve",
        auth=alice,
        canonical_model="alibaba/qwen-max",
    )
    rows = runtimes.performances_for_agent("official/pi-default", alice)
    assert [r["suite_run_id"] for r in rows] == ["s_bob"]
    meta = results.serve_suite_meta(suite_run_id="s_bob", auth=bob)
    assert meta["config_fingerprint"] == fingerprint
    assert str(meta["job_overlay"]["agent_profiles"]["solver"]["agent_ref"]).startswith(
        "official/pi-default@0.1.0+"
    )


def test_agent_org_owner_attaches_without_request(tmp_path: Path) -> None:
    packages, results, requests, runtimes = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    _publish_agent(
        packages, tmp_path, package_id="official/pi-default", org_id="official", owner="alice"
    )
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    _upload(
        results,
        tmp_path,
        suite_run_id="s_alice",
        dataset_id="official/gaia",
        user_id="alice",
        agent_profiles={"solver": dict(PI)},
    )
    out = requests.apply(
        kind="agent_performance",
        suite_run_id="s_alice",
        auth=alice,
        agent="official/pi-default@0.1.0",
    )
    assert out.get("direct_attach") is True
    assert out.get("request") is None
    assert requests.inbox(auth=alice)["items"] == []
    assert [
        r["suite_run_id"] for r in runtimes.performances_for_agent("official/pi-default", alice)
    ] == ["s_alice"]


def test_batch_decide_and_unknown_kind(tmp_path: Path) -> None:
    packages, results, requests, _rt = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    _upload(results, tmp_path, suite_run_id="s1", dataset_id="official/gaia", user_id="bob")
    _upload(results, tmp_path, suite_run_id="s2", dataset_id="official/gaia", user_id="bob")
    a = requests.apply(kind="leaderboard_list", suite_run_id="s1", auth=bob)
    b = requests.apply(kind="leaderboard_list", suite_run_id="s2", auth=bob)
    requests.decide(request_ids=[a["request_id"], b["request_id"]], action="approve", auth=alice)
    board = results.list_suites(auth=alice, dataset_id="official/gaia", board=True)
    assert {i["suite_run_id"] for i in board["items"]} == {"s1", "s2"}
    with pytest.raises(RegistryAppError, match="unknown request kind"):
        requests.apply(kind="org_join", suite_run_id="s1", auth=bob)


def test_performance_approve_private_suite_and_mismatch(tmp_path: Path) -> None:
    packages, results, requests, runtimes = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    _publish_agent(
        packages, tmp_path, package_id="official/pi-default", org_id="official", owner="alice"
    )
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    _upload(
        results,
        tmp_path,
        suite_run_id="s_priv",
        dataset_id="official/gaia",
        user_id="bob",
        agent_profiles={"solver": dict(PI)},
        visibility="private",
    )
    applied = requests.apply(
        kind="agent_performance",
        suite_run_id="s_priv",
        auth=bob,
        agent="official/pi-default@0.1.0",
    )
    decided = requests.decide(
        request_ids=[applied["request_id"]],
        action="approve",
        auth=alice,
        canonical_model="alibaba/qwen-max",
    )
    assert decided["items"][0]["status"] == "approved"
    meta = results.serve_suite_meta(suite_run_id="s_priv", auth=bob)
    assert str(meta["job_overlay"]["agent_profiles"]["solver"]["agent_ref"]).startswith(
        "official/pi-default@0.1.0+"
    )
    assert runtimes.performances_for_agent("official/pi-default", alice) == []

    _upload(
        results,
        tmp_path,
        suite_run_id="s_mis",
        dataset_id="official/gaia",
        user_id="bob",
        agent_profiles={
            "solver": {
                **PI,
                "extensions": [{"plugin": "acp", "options": {"entry": "codex"}}],
            }
        },
    )
    bad = requests.apply(
        kind="agent_performance",
        suite_run_id="s_mis",
        auth=bob,
        agent="official/pi-default@0.1.0",
    )
    overlay_before = results.serve_suite_meta(suite_run_id="s_mis", auth=bob)["job_overlay"]
    with pytest.raises(RegistryAppError, match="match"):
        requests.decide(
            request_ids=[bad["request_id"]],
            action="approve",
            auth=alice,
            canonical_model="alibaba/qwen-max",
        )
    still = results.inbox.get_resource_request(bad["request_id"])
    assert still is not None and still.status == "pending"
    after = results.serve_suite_meta(suite_run_id="s_mis", auth=bob)
    assert after["job_overlay"] == overlay_before
    assert "agent_ref" not in after["job_overlay"]["agent_profiles"]["solver"]


def test_delete_and_replace_drop_requests_and_consent(tmp_path: Path) -> None:
    packages, results, requests, runtimes = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    _publish_agent(
        packages, tmp_path, package_id="official/pi-default", org_id="official", owner="alice"
    )
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    _upload(results, tmp_path, suite_run_id="s_drop", dataset_id="official/gaia", user_id="bob")
    listing = requests.apply(kind="leaderboard_list", suite_run_id="s_drop", auth=bob)
    assert [i["request_id"] for i in requests.inbox(auth=alice)["items"]] == [listing["request_id"]]
    results.delete_suite(suite_run_id="s_drop", with_attempts=False, auth=bob)
    assert requests.inbox(auth=alice)["items"] == []
    with pytest.raises(RegistryAppError) as missing:
        requests.decide(request_ids=[listing["request_id"]], action="approve", auth=alice)
    assert missing.value.http_status == 404

    _upload(
        results,
        tmp_path,
        suite_run_id="s_keep",
        dataset_id="official/gaia",
        user_id="alice",
        agent_profiles={"solver": dict(PI)},
    )
    requests.apply(
        kind="agent_performance",
        suite_run_id="s_keep",
        auth=alice,
        agent="official/pi-default@0.1.0",
    )
    assert [
        r["suite_run_id"] for r in runtimes.performances_for_agent("official/pi-default", alice)
    ] == ["s_keep"]
    _upload(
        results,
        tmp_path,
        suite_run_id="s_keep",
        dataset_id="official/gaia",
        user_id="alice",
        agent_profiles={
            "solver": {**PI, "agent_ref": "official/pi-default@0.1.0+sha256:aaaaaaaaaaaa"}
        },
        replace=True,
    )
    assert results.inbox.list_agent_consents("s_keep") == []
    assert runtimes.performances_for_agent("official/pi-default", alice) == []


def test_hide_processed_inbox_is_per_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGEVAL_REGISTRY_MAINTAINERS", "alice,carol")
    packages, results, requests, _rt = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    carol = TokenInfo(scopes=frozenset({"results:upload"}), user_id="carol")
    _upload(results, tmp_path, suite_run_id="s_hide", dataset_id="official/gaia", user_id="bob")
    listing = requests.apply(kind="leaderboard_list", suite_run_id="s_hide", auth=bob)
    requests.decide(request_ids=[listing["request_id"]], action="reject", auth=alice)
    assert listing["request_id"] in {i["request_id"] for i in requests.inbox(auth=alice)["items"]}
    hidden = requests.hide(request_ids=[listing["request_id"]], auth=alice)
    assert hidden["ok"] is True
    assert requests.inbox(auth=alice)["items"] == []
    _upload(
        results,
        tmp_path,
        suite_run_id="s_pi",
        dataset_id="official/gaia",
        user_id="bob",
        agent_profiles={"solver": dict(PI)},
    )
    perf = requests.apply(kind="agent_performance", suite_run_id="s_pi", auth=bob, agent="pi")
    requests.decide(request_ids=[perf["request_id"]], action="reject", auth=alice)
    requests.hide(request_ids=[perf["request_id"]], auth=alice)
    assert perf["request_id"] in {i["request_id"] for i in requests.inbox(auth=carol)["items"]}
    requests.hide(request_ids=[perf["request_id"]], auth=carol)
    assert requests.inbox(auth=carol)["items"] == []


def test_performance_request_stores_canonical_and_approve_may_override(
    tmp_path: Path,
) -> None:
    packages, results, requests, runtimes = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    _publish_agent(
        packages, tmp_path, package_id="official/pi-default", org_id="official", owner="alice"
    )
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    _upload(
        results,
        tmp_path,
        suite_run_id="s_model",
        dataset_id="official/gaia",
        user_id="bob",
        agent_profiles={"solver": {**PI, "model": "dashscope/qwen-max"}},
    )
    applied = requests.apply(
        kind="agent_performance",
        suite_run_id="s_model",
        auth=bob,
        agent="official/pi-default@0.1.0",
        canonical_model="alibaba/qwen-max",
    )
    assert applied["status"] == "pending"
    assert applied["canonical_model"] == "alibaba/qwen-max"
    assert runtimes.performances_for_agent("official/pi-default", alice) == []
    requests.decide(
        request_ids=[applied["request_id"]],
        action="approve",
        auth=alice,
        canonical_model="alibaba/qwen-flash",
    )
    rows = runtimes.performances_for_agent("official/pi-default", alice)
    assert [r["suite_run_id"] for r in rows] == ["s_model"]
    assert rows[0]["model"] == "dashscope/qwen-max"
    assert rows[0]["canonical_model"] == "alibaba/qwen-flash"


def test_owner_direct_attach_records_canonical_bucket(tmp_path: Path) -> None:
    packages, results, requests, runtimes = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    _publish_agent(
        packages, tmp_path, package_id="official/pi-default", org_id="official", owner="alice"
    )
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    _upload(
        results,
        tmp_path,
        suite_run_id="s_owner",
        dataset_id="official/gaia",
        user_id="alice",
        agent_profiles={"solver": {**PI, "model": "openrouter/deepseek/deepseek-v4-flash"}},
    )
    attached = requests.apply(
        kind="agent_performance",
        suite_run_id="s_owner",
        auth=alice,
        agent="official/pi-default@0.1.0",
        canonical_model="deepseek/deepseek-v4-flash",
    )
    assert attached.get("direct_attach") is True
    assert attached.get("canonical_model") == "deepseek/deepseek-v4-flash"
    rows = runtimes.performances_for_agent("official/pi-default", alice)
    assert rows[0]["canonical_model"] == "deepseek/deepseek-v4-flash"
    assert rows[0]["model"] == "openrouter/deepseek/deepseek-v4-flash"


def test_approve_performance_without_canonical_fails_closed(tmp_path: Path) -> None:
    packages, results, requests, runtimes = _svcs(tmp_path)
    _publish_dataset(
        packages, tmp_path, dataset_id="official/gaia", org_id="official", owner="alice"
    )
    _publish_agent(
        packages, tmp_path, package_id="official/pi-default", org_id="official", owner="alice"
    )
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    _upload(
        results,
        tmp_path,
        suite_run_id="s_bare",
        dataset_id="official/gaia",
        user_id="bob",
        agent_profiles={"solver": {**PI, "model": "dashscope/qwen-max"}},
    )
    applied = requests.apply(
        kind="agent_performance",
        suite_run_id="s_bare",
        auth=bob,
        agent="official/pi-default@0.1.0",
    )
    assert applied["status"] == "pending"
    assert not applied.get("canonical_model")
    with pytest.raises(RegistryAppError) as missing:
        requests.decide(request_ids=[applied["request_id"]], action="approve", auth=alice)
    assert missing.value.http_status == 400
    assert missing.value.error == "invalid_request"
    assert runtimes.performances_for_agent("official/pi-default", alice) == []
    requests.decide(
        request_ids=[applied["request_id"]],
        action="approve",
        auth=alice,
        canonical_model="alibaba/qwen-max",
    )
    rows = runtimes.performances_for_agent("official/pi-default", alice)
    assert rows[0]["canonical_model"] == "alibaba/qwen-max"
    assert rows[0]["model"] == "dashscope/qwen-max"
