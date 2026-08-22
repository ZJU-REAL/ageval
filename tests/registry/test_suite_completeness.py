"""Leaderboard completeness is computed at suite upload (not SPA-only)."""

from __future__ import annotations

import shutil
from pathlib import Path

from services.registry.access import AccessPolicy
from services.registry.package_service import PackageService
from services.registry.result_service import ResultService
from services.registry.store import MemoryBlobStore, MetadataStore, TokenInfo

from ageval.registry.archive import MEDIA_TYPE, build_archive
from ageval.registry.digest import compute_package_digest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"


def _services(tmp_path: Path) -> tuple[PackageService, ResultService]:
    meta = MetadataStore(tmp_path / "meta.sqlite3")
    blobs = MemoryBlobStore()
    access = AccessPolicy(meta=meta)
    packages = PackageService(meta, blobs, access, max_upload=64 * 1024 * 1024)
    results = ResultService(meta, blobs, access, max_upload=64 * 1024 * 1024)
    return packages, results


def _as_path(tmp_path: Path, data: bytes, name: str = "blob.bin") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _publish_release(packages: PackageService, tmp_path: Path) -> None:
    archive, blob_digest, size = build_archive(FIXTURE)
    packages.meta.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    packages.publish(
        meta={
            "dataset_id": "test/publish-min",
            "version": "0.1.0",
            "package_digest": compute_package_digest(FIXTURE),
            "blob_digest": blob_digest,
            "media_type": MEDIA_TYPE,
            "visibility": "public",
            "org_id": "acme",
            "size": size,
        },
        archive=_as_path(tmp_path, archive, "release.tar.gz"),
        auth=auth,
    )


def _suite_meta(
    tmp_path: Path,
    *,
    suite_run_id: str,
    task_refs: list[dict[str, object]],
    version: str = "0.1.0",
) -> tuple[dict[str, object], Path]:
    archive = b"suite-archive"
    import hashlib

    blob = f"sha256:{hashlib.sha256(archive).hexdigest()}"
    return (
        {
            "suite_run_id": suite_run_id,
            "dataset_id": "test/publish-min",
            "dataset_version": version,
            "visibility": "public",
            "blob_digest": blob,
            "size": len(archive),
            "pass_rate": 0.0,
            "mean_score": 0.0,
            "metrics": {"n_tasks": len(task_refs)},
            "task_refs": task_refs,
        },
        _as_path(tmp_path, archive, f"{suite_run_id}.bin"),
    )


def test_fail_on_all_tasks_is_complete_and_on_board(tmp_path: Path) -> None:
    packages, results = _services(tmp_path)
    _publish_release(packages, tmp_path)
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    meta, archive = _suite_meta(
        tmp_path,
        suite_run_id="suite_fail_all",
        task_refs=[{"task_id": "hello", "status": "FAIL", "score": 0.0}],
    )
    payload = results.upload_suite(meta=meta, archive=archive, auth=auth)
    assert payload["complete"] is True
    assert payload["bound_kind"] == "release"
    assert payload["board_listed"] is False
    board = results.list_suites(auth=auth, dataset_id="test/publish-min", board=True)
    assert board["items"] == []
    results.meta.set_suite_board_listed("suite_fail_all", True)
    board = results.list_suites(auth=auth, dataset_id="test/publish-min", board=True)
    assert [i["suite_run_id"] for i in board["items"]] == ["suite_fail_all"]


def test_missing_task_is_incomplete_hidden_from_board(tmp_path: Path) -> None:
    packages, results = _services(tmp_path)
    _publish_release(packages, tmp_path)
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    meta, archive = _suite_meta(
        tmp_path,
        suite_run_id="suite_missing",
        task_refs=[],
    )
    payload = results.upload_suite(meta=meta, archive=archive, auth=auth)
    assert payload["complete"] is False
    board = results.list_suites(auth=auth, dataset_id="test/publish-min", board=True)
    jobs = results.list_suites(auth=auth, dataset_id="test/publish-min", board=False)
    assert board["items"] == []
    assert [i["suite_run_id"] for i in jobs["items"]] == ["suite_missing"]


def test_draft_bound_suite_stays_off_public_board(tmp_path: Path) -> None:
    packages, results = _services(tmp_path)
    packages.meta.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    archive, blob_digest, size = build_archive(FIXTURE)
    alice = TokenInfo(scopes=frozenset({"registry:publish", "results:upload"}), user_id="alice")
    packages.publish(
        meta={
            "dataset_id": "test/publish-min",
            "version": "0.1.0",
            "package_digest": compute_package_digest(FIXTURE),
            "blob_digest": blob_digest,
            "media_type": MEDIA_TYPE,
            "visibility": "private",
            "org_id": "acme",
            "size": size,
            "slot": "draft",
        },
        archive=_as_path(tmp_path, archive, "draft.tar.gz"),
        auth=alice,
    )
    meta, sarch = _suite_meta(
        tmp_path,
        suite_run_id="suite_draft",
        version="0.1.0",
        task_refs=[{"task_id": "hello", "status": "PASS", "score": 1.0}],
    )
    payload = results.upload_suite(meta=meta, archive=sarch, auth=alice)
    assert payload["bound_kind"] == "draft"
    assert payload["complete"] is True
    board = results.list_suites(auth=alice, dataset_id="test/publish-min", board=True)
    jobs = results.list_suites(auth=alice, dataset_id="test/publish-min", board=False)
    assert board["items"] == []
    assert jobs["items"][0]["suite_run_id"] == "suite_draft"


def test_suite_plugins_and_uploaded_by_me_filter(tmp_path: Path) -> None:
    packages, results = _services(tmp_path)
    _publish_release(packages, tmp_path)
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    meta, archive = _suite_meta(
        tmp_path,
        suite_run_id="suite_alice",
        task_refs=[{"task_id": "hello", "status": "PASS", "score": 1.0}],
    )
    meta["plugins"] = [
        {"plugin_id": "nooa", "version": "0.1.0"},
        {"plugin_id": "default"},
        {"plugin_id": "ACP"},
        {"plugin_id": "openai-http"},
        {"plugin_id": "nooa"},
    ]
    payload = results.upload_suite(meta=meta, archive=archive, auth=alice)
    assert payload["plugins"] == [{"plugin_id": "nooa", "version": "0.1.0"}]
    meta_b, arch_b = _suite_meta(
        tmp_path,
        suite_run_id="suite_bob",
        task_refs=[{"task_id": "hello", "status": "FAIL", "score": 0.0}],
    )
    results.upload_suite(meta=meta_b, archive=arch_b, auth=bob)
    mine = results.list_suites(auth=alice, dataset_id="test/publish-min", uploaded_by="me")
    assert [i["suite_run_id"] for i in mine["items"]] == ["suite_alice"]
    empty = results.list_suites(
        auth=TokenInfo(scopes=frozenset({"results:upload"}), user_id=""),
        dataset_id="test/publish-min",
        uploaded_by="me",
    )
    assert empty["items"] == []


def test_later_draft_task_does_not_drop_old_release_run(tmp_path: Path) -> None:
    packages, results = _services(tmp_path)
    _publish_release(packages, tmp_path)
    auth = TokenInfo(scopes=frozenset({"registry:publish", "results:upload"}), user_id="alice")
    meta, archive = _suite_meta(
        tmp_path,
        suite_run_id="suite_release",
        task_refs=[{"task_id": "hello", "status": "PASS", "score": 1.0}],
    )
    results.upload_suite(meta=meta, archive=archive, auth=auth)
    results.meta.set_suite_board_listed("suite_release", True)
    # Later draft adds a task; stored release fingerprint must not be rewritten.
    wider = tmp_path / "wider"
    shutil.copytree(FIXTURE, wider)
    world = wider / "tasks" / "world"
    world.mkdir()
    hello = FIXTURE / "tasks" / "hello"
    (world / "task.yaml").write_text(
        (hello / "task.yaml")
        .read_text(encoding="utf-8")
        .replace("task_id: hello", "task_id: world"),
        encoding="utf-8",
    )
    shutil.copy(hello / "run.py", world / "run.py")
    shutil.copy(hello / "evaluator.py", world / "evaluator.py")
    pkg, blob_digest, size = build_archive(wider)
    packages.publish(
        meta={
            "dataset_id": "test/publish-min",
            "version": "0.1.0",
            "package_digest": compute_package_digest(wider),
            "blob_digest": blob_digest,
            "media_type": MEDIA_TYPE,
            "visibility": "private",
            "org_id": "acme",
            "size": size,
            "slot": "draft",
        },
        archive=_as_path(tmp_path, pkg, "wider.tar.gz"),
        auth=auth,
    )
    board = results.list_suites(auth=auth, dataset_id="test/publish-min", board=True)
    assert [i["suite_run_id"] for i in board["items"]] == ["suite_release"]
    assert board["items"][0]["complete"] is True
    assert board["items"][0]["bound_kind"] == "release"

    draft_meta, draft_arch = _suite_meta(
        tmp_path,
        suite_run_id="suite_new_draft",
        version="draft",
        task_refs=[{"task_id": "hello", "status": "PASS", "score": 1.0}],
    )
    new_payload = results.upload_suite(meta=draft_meta, archive=draft_arch, auth=auth)
    assert new_payload["bound_kind"] == "draft"
    assert new_payload["complete"] is False
    board_after = results.list_suites(auth=auth, dataset_id="test/publish-min", board=True)
    assert [i["suite_run_id"] for i in board_after["items"]] == ["suite_release"]


def test_non_entitled_uploader_cannot_bind_private_draft(tmp_path: Path) -> None:
    packages, results = _services(tmp_path)
    packages.meta.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    archive, blob_digest, size = build_archive(FIXTURE)
    alice = TokenInfo(scopes=frozenset({"registry:publish", "results:upload"}), user_id="alice")
    packages.publish(
        meta={
            "dataset_id": "test/publish-min",
            "version": "0.1.0",
            "package_digest": compute_package_digest(FIXTURE),
            "blob_digest": blob_digest,
            "media_type": MEDIA_TYPE,
            "visibility": "private",
            "org_id": "acme",
            "size": size,
            "slot": "draft",
        },
        archive=_as_path(tmp_path, archive, "priv-draft.tar.gz"),
        auth=alice,
    )
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    meta, sarch = _suite_meta(
        tmp_path,
        suite_run_id="suite_stranger",
        version="draft",
        task_refs=[{"task_id": "hello", "status": "PASS", "score": 1.0}],
    )
    payload = results.upload_suite(meta=meta, archive=sarch, auth=bob)
    assert payload["bound_kind"] == "unknown"
    assert payload["complete"] is False
    assert "task_set_digest" not in payload

    fallback_meta, fallback_arch = _suite_meta(
        tmp_path,
        suite_run_id="suite_stranger_fallback",
        version="0.1.0",
        task_refs=[{"task_id": "hello", "status": "PASS", "score": 1.0}],
    )
    fallback = results.upload_suite(meta=fallback_meta, archive=fallback_arch, auth=bob)
    assert fallback["bound_kind"] == "unknown"
    assert fallback["complete"] is False
    assert "task_set_digest" not in fallback
