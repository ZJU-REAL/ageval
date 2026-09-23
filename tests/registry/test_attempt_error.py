"""Uploaded attempts carry error and limit; a row from before does not."""

from __future__ import annotations

import hashlib
from pathlib import Path

from services.registry.access import AccessPolicy
from services.registry.result_service import ResultService
from services.registry.store import (
    AttemptResultRow,
    MemoryBlobStore,
    TokenInfo,
    attempt_to_dict,
    now,
)
from services.registry.store_schema import open_sqlite_stores

_ERROR = {"phase": "evaluate", "title": "Judge response empty", "message": "judge returned no text"}


def _service(tmp_path: Path) -> ResultService:
    meta = open_sqlite_stores(tmp_path / "meta.sqlite3")
    blobs = MemoryBlobStore()
    access = AccessPolicy(orgs=meta.orgs, packages=meta.packages, results=meta.results)
    return ResultService(
        meta.results,
        meta.packages,
        meta.orgs,
        meta.inbox,
        blobs,
        access,
        max_upload=1024 * 1024,
    )


def _archive(tmp_path: Path, name: str) -> tuple[Path, str, int]:
    raw = f"attempt-{name}".encode()
    path = tmp_path / f"{name}.bin"
    path.write_bytes(raw)
    return path, "sha256:" + hashlib.sha256(raw).hexdigest(), len(raw)


def test_upload_list_and_detail_carry_error_and_limit(tmp_path: Path) -> None:
    results = _service(tmp_path)
    auth = TokenInfo(scopes=frozenset({"results:read", "results:upload"}), user_id="alice")
    archive, digest, size = _archive(tmp_path, "run_err")
    uploaded = results.upload_attempt(
        meta={
            "run_id": "run_err",
            "dataset_id": "test/script-error",
            "dataset_version": "0.1.0",
            "task_id": "eval-script-error",
            "lock_digest": "sha256:abc",
            "status": "ERROR",
            "visibility": "public",
            "blob_digest": digest,
            "size": size,
            "error": _ERROR,
            "limit": None,
        },
        archive=archive,
        auth=auth,
    )
    assert uploaded["error"] == _ERROR
    assert uploaded["limit"] is None

    listed = results.list_attempts(auth=auth, dataset_id="test/script-error")
    item = listed["items"][0]
    assert item["error"] == _ERROR
    assert item["limit"] is None
    detail = results.serve_attempt_meta(run_id="run_err", auth=auth)
    assert detail["error"] == _ERROR
    assert detail["limit"] is None

    archive2, digest2, size2 = _archive(tmp_path, "run_limit")
    limited = results.upload_attempt(
        meta={
            "run_id": "run_limit",
            "dataset_id": "test/script-error",
            "dataset_version": "0.1.0",
            "task_id": "wall-hit",
            "lock_digest": "sha256:abc",
            "status": "FAIL",
            "visibility": "public",
            "blob_digest": digest2,
            "size": size2,
            "score": 0.3,
            "error": None,
            "limit": "wall_time_seconds",
        },
        archive=archive2,
        auth=auth,
    )
    assert limited["error"] is None
    assert limited["limit"] == "wall_time_seconds"


def test_row_without_error_or_limit_returns_null(tmp_path: Path) -> None:
    meta = open_sqlite_stores(tmp_path / "meta.sqlite3")
    row = AttemptResultRow(
        run_id="run_old",
        dataset_id="test/script-error",
        dataset_version="0.1.0",
        task_id="alpha",
        lock_digest="sha256:abc",
        status="PASS",
        visibility="public",
        blob_digest="sha256:" + "a" * 64,
        size=4,
        created_at=now(),
    )
    meta.results.insert_attempt(row)
    got = meta.results.get_attempt("run_old")
    assert got is not None
    payload = attempt_to_dict(got)
    assert payload["error"] is None
    assert payload["limit"] is None
