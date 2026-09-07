"""Append one Attempt onto an existing suite row (not whole-row --replace)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from services.registry.access import AccessPolicy
from services.registry.errors import RegistryAppError
from services.registry.package_service import PackageService
from services.registry.result_service import ResultService
from services.registry.store import MemoryBlobStore, TokenInfo
from services.registry.store_schema import (
    open_sqlite_stores,
)

from ageval.registry.archive import MEDIA_TYPE, build_archive
from ageval.registry.digest import compute_package_digest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"


def _services(tmp_path: Path) -> ResultService:
    meta = open_sqlite_stores(tmp_path / "meta.sqlite3")
    blobs = MemoryBlobStore()
    access = AccessPolicy(orgs=meta.orgs, packages=meta.packages, results=meta.results)
    packages = PackageService(meta.packages, meta.orgs, blobs, access, max_upload=64 * 1024 * 1024)
    archive, blob_digest, size = build_archive(FIXTURE)
    packages.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
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
    return ResultService(
        meta.results,
        meta.packages,
        meta.orgs,
        meta.inbox,
        blobs,
        access,
        max_upload=64 * 1024 * 1024,
    )


def _as_path(tmp_path: Path, data: bytes, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _blob(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _suite_archive(tmp_path: Path, suite_run_id: str) -> tuple[dict[str, object], Path]:
    raw = b"suite-archive"
    return (
        {
            "suite_run_id": suite_run_id,
            "dataset_id": "test/publish-min",
            "dataset_version": "0.1.0",
            "visibility": "public",
            "blob_digest": _blob(raw),
            "size": len(raw),
            "pass_rate": 0.0,
            "mean_score": 0.0,
            "exit_code": 2,
            "metrics": {
                "n_tasks": 1,
                "n_pass": 0,
                "n_error": 1,
                "pass_rate": 0.0,
                "mean_score": 0.0,
            },
            "task_refs": [
                {"task_id": "hello", "status": "ERROR", "score": None, "run_id": "oldrun"}
            ],
            "config_fingerprint": "sha256:suite-fp",
        },
        _as_path(tmp_path, raw, f"{suite_run_id}.bin"),
    )


def _upload_attempt(
    results: ResultService,
    tmp_path: Path,
    run_id: str,
    *,
    auth: TokenInfo,
    status: str = "PASS",
    suite_run_id: str = "",
    dataset_id: str = "test/publish-min",
) -> None:
    raw = f"attempt-{run_id}".encode()
    results.upload_attempt(
        meta={
            "run_id": run_id,
            "dataset_id": dataset_id,
            "dataset_version": "0.1.0",
            "task_id": "hello",
            "lock_digest": "sha256:x",
            "status": status,
            "visibility": "public",
            "blob_digest": _blob(raw),
            "size": len(raw),
            "suite_run_id": suite_run_id,
        },
        archive=_as_path(tmp_path, raw, f"{run_id}.bin"),
        auth=auth,
    )


def test_upload_suite_requires_dataset_version(tmp_path: Path) -> None:
    results = _services(tmp_path)
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    meta, archive = _suite_archive(tmp_path, "suite_no_ver")
    del meta["dataset_version"]
    with pytest.raises(RegistryAppError, match="dataset_version"):
        results.upload_suite(meta=meta, archive=archive, auth=auth)


def test_append_slot_updates_metrics_and_keeps_old_attempt(tmp_path: Path) -> None:
    results = _services(tmp_path)
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    meta, archive = _suite_archive(tmp_path, "suite_slot")
    results.upload_suite(meta=meta, archive=archive, auth=auth)
    _upload_attempt(
        results, tmp_path, "oldrun", auth=auth, status="ERROR", suite_run_id="suite_slot"
    )
    _upload_attempt(
        results, tmp_path, "newrun", auth=auth, status="PASS", suite_run_id="suite_slot"
    )

    payload = results.append_suite_slot(
        suite_run_id="suite_slot",
        body={
            "task_id": "hello",
            "run_id": "newrun",
            "attempt_index": 0,
            "pass_rate": 1.0,
            "mean_score": 1.0,
            "exit_code": 0,
            "metrics": {
                "n_tasks": 1,
                "n_pass": 1,
                "n_error": 0,
                "pass_rate": 1.0,
                "mean_score": 1.0,
            },
            "task_refs": [
                {
                    "task_id": "hello",
                    "status": "PASS",
                    "score": 1.0,
                    "run_id": "newrun",
                    "previous": [
                        {
                            "run_id": "oldrun",
                            "status": "ERROR",
                            "score": None,
                            "attempt_index": 0,
                            "replaced_at": "t",
                        }
                    ],
                }
            ],
            "config_fingerprint": "sha256:suite-fp",
        },
        auth=auth,
    )
    assert payload["amended"] is True
    assert payload["pass_rate"] == 1.0
    assert payload["complete"] is True
    assert payload["task_refs"][0]["run_id"] == "newrun"
    assert payload["task_refs"][0]["previous"][0]["run_id"] == "oldrun"
    # Old row + blob still GET.
    old = results.serve_attempt_meta(run_id="oldrun", auth=auth)
    assert old["run_id"] == "oldrun"
    assert old["status"] == "ERROR"
    got = results.get_suite("suite_slot")
    assert got is not None
    assert got.created_at == results.get_suite("suite_slot").created_at


def test_append_slot_refuses_replace_flag_and_missing_run(tmp_path: Path) -> None:
    results = _services(tmp_path)
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    meta, archive = _suite_archive(tmp_path, "suite_refuse")
    results.upload_suite(meta=meta, archive=archive, auth=auth)

    with pytest.raises(RegistryAppError, match="must not use replace"):
        results.append_suite_slot(
            suite_run_id="suite_refuse",
            body={"replace": True, "task_id": "hello", "run_id": "x"},
            auth=auth,
        )
    with pytest.raises(RegistryAppError, match="run_id is missing"):
        results.append_suite_slot(
            suite_run_id="suite_refuse",
            body={
                "task_id": "hello",
                "run_id": "ghost",
                "task_refs": [{"task_id": "hello", "run_id": "ghost", "status": "PASS"}],
                "metrics": {},
            },
            auth=auth,
        )


def test_append_slot_refuses_foreign_run_and_fingerprint(tmp_path: Path) -> None:
    results = _services(tmp_path)
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    meta, archive = _suite_archive(tmp_path, "suite_a")
    results.upload_suite(meta=meta, archive=archive, auth=auth)
    _upload_attempt(results, tmp_path, "foreign", auth=auth, suite_run_id="other-suite")

    with pytest.raises(RegistryAppError, match="another suite"):
        results.append_suite_slot(
            suite_run_id="suite_a",
            body={
                "task_id": "hello",
                "run_id": "foreign",
                "task_refs": [{"task_id": "hello", "run_id": "foreign", "status": "PASS"}],
                "metrics": {},
            },
            auth=auth,
        )

    _upload_attempt(results, tmp_path, "newrun", auth=auth, suite_run_id="suite_a")
    _upload_attempt(results, tmp_path, "id0", auth=auth, suite_run_id="suite_k")
    _upload_attempt(results, tmp_path, "id2", auth=auth, suite_run_id="suite_k")
    _upload_attempt(results, tmp_path, "id1new", auth=auth, suite_run_id="suite_k")
    meta_k, archive_k = _suite_archive(tmp_path, "suite_k")
    meta_k["task_refs"] = [
        {
            "task_id": "hello",
            "status": "ERROR",
            "run_id": "id0",
            "attempt_run_ids": ["id0", "id2", "id1old"],
        }
    ]
    results.upload_suite(meta=meta_k, archive=archive_k, auth=auth)
    payload = results.append_suite_slot(
        suite_run_id="suite_k",
        body={
            "task_id": "hello",
            "run_id": "id1new",
            "attempt_index": 1,
            "config_fingerprint": "sha256:suite-fp",
            "pass_rate": 0.0,
            "mean_score": 0.0,
            "metrics": {},
            "task_refs": [
                {
                    "task_id": "hello",
                    "status": "PASS",
                    "run_id": "id1new",
                    "attempt_run_ids": ["id0", "id1new", "id2"],
                    "previous": [
                        {
                            "run_id": "id1old",
                            "status": "ERROR",
                            "attempt_index": 1,
                        }
                    ],
                }
            ],
        },
        auth=auth,
    )
    assert payload["task_refs"][0]["previous"][0]["run_id"] == "id1old"

    with pytest.raises(RegistryAppError, match="config_fingerprint"):
        results.append_suite_slot(
            suite_run_id="suite_a",
            body={
                "task_id": "hello",
                "run_id": "newrun",
                "config_fingerprint": "sha256:other",
                "task_refs": [
                    {
                        "task_id": "hello",
                        "run_id": "newrun",
                        "status": "PASS",
                        "previous": [{"run_id": "oldrun", "status": "ERROR"}],
                    }
                ],
                "metrics": {},
            },
            auth=auth,
        )
