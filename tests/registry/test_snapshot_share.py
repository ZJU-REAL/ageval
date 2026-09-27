"""Snapshot share: capability URL, not catalog ACL."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from services.registry.app import build_default_state, make_handler
from services.registry.blob_io import sha256_file
from services.registry.tokens import DEFAULT_LOGIN_SCOPES

from ageval.registry.client import RegistryClient, RegistryError
from ageval.registry.share_snapshot import snapshot_has_plaintext_secret


def _gzip_tar(members: dict[str, bytes]) -> bytes:
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(tar_buf.getvalue())
    return out.getvalue()


def _summary(*, api_key: str = "OPENAI_API_KEY") -> dict:
    return {
        "suite_run_id": "suite0001",
        "dataset_id": "acme/demo",
        "dataset_version": "0.1.0",
        "status": "finished",
        "exit_code": 0,
        "pass_rate": 1.0,
        "mean_score": 1.0,
        "metrics": {"pass_rate": 1.0, "mean_score": 1.0},
        "agent_label": "pi",
        "model_label": "demo",
        "task_refs": [{"task_id": "hello", "status": "PASS", "score": 1, "run_id": "run000001"}],
        "job_overlay": {"solver": {"api_key": api_key, "model": "demo"}},
    }


def _archive(tmp: Path, *, api_key: str = "OPENAI_API_KEY", name: str = "snapshot.tar.gz") -> Path:
    summary = json.dumps(_summary(api_key=api_key), sort_keys=True).encode()
    marker = json.dumps(
        {"kind": "snapshot-share", "version": 1, "suite_run_id": "suite0001"}
    ).encode()
    raw = _gzip_tar(
        {
            "snapshot-share.json": marker,
            ".ageval/suite-runs/suite0001/summary.json": summary,
            ".ageval/runs/run000001/result.json": b'{"status":"PASS","score":1}\n',
            ".ageval/runs/run000001/summary.json": b'{"status":"PASS"}\n',
            ".ageval/runs/run000001/trajectory.jsonl": b'{"type":"message","text":"hi"}\n',
        }
    )
    path = tmp / name
    path.write_bytes(raw)
    return path


def _count(state, table: str) -> int:
    with state.stores.results._connect() as conn:
        cur = state.stores.results._exec(conn, f"SELECT COUNT(*) AS n FROM {table}")
        row = cur.fetchone()
    return int(row["n"])


@pytest.fixture()
def registry_server(tmp_path: Path):
    state, token = build_default_state(
        tmp_path / "reg",
        bootstrap_token="owner-token",
        memory_blob=True,
    )
    state.tokens.add("mallory-token", DEFAULT_LOGIN_SCOPES, github_user="mallory")
    handler = make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield {"url": url, "token": token, "state": state}
    server.shutdown()


def _upload(client: RegistryClient, archive: Path) -> dict:
    return client.create_snapshot_share(
        suite_run_id="suite0001",
        dataset_id="acme/demo",
        dataset_version="0.1.0",
        blob_digest=sha256_file(archive),
        size=archive.stat().st_size,
        archive=archive,
    )


def test_plaintext_secret_scan_reads_decompressed_members(tmp_path: Path) -> None:
    secret = _archive(tmp_path, api_key="sk-supersecretvalue", name="secret.tar.gz")
    locator = tmp_path / "locator.tar.gz"
    locator.write_bytes(
        _gzip_tar(
            {
                "snapshot-share.json": b'{"kind":"snapshot-share"}',
                "notes.json": b'{"api_key":"OPENAI_API_KEY","token":"${OPENAI_API_KEY}"}',
            }
        )
    )
    assert snapshot_has_plaintext_secret(secret) is True
    assert snapshot_has_plaintext_secret(locator) is False


def test_create_is_anonymous_read_and_does_not_touch_catalog(
    registry_server, tmp_path: Path
) -> None:
    state = registry_server["state"]
    owner = RegistryClient(registry_server["url"], token=registry_server["token"])
    created = _upload(owner, _archive(tmp_path))
    token = created["token"]
    assert created["path"] == f"/s/{token}"
    assert created["kind"] == "snapshot-share"
    assert "visibility" not in created
    assert "board_listed" not in created
    assert "result_shares" not in created
    assert _count(state, "suite_results") == 0
    assert _count(state, "result_shares") == 0
    assert _count(state, "snapshot_shares") == 1

    anon = RegistryClient(registry_server["url"], token=None)
    view = anon.get_snapshot_share(token)
    assert view["suite_run_id"] == "suite0001"
    assert view["task_refs"][0]["has_attempt_content"] is True
    assert view["task_refs"][0]["status"] == "PASS"

    status, raw, _ = anon._request(
        "GET",
        f"/v1/shares/{token}/attempts/run000001/files",
        auth=False,
    )
    files = json.loads(raw.decode())
    assert status == 200
    paths = {item["path"] for item in files["items"]}
    assert ".ageval/runs/run000001/result.json" in paths

    file_status, file_raw, _ = anon._request(
        "GET",
        f"/v1/shares/{token}/attempts/run000001/files/.ageval/runs/run000001/result.json",
        auth=False,
    )
    assert file_status == 200
    body = json.loads(file_raw.decode())
    assert "PASS" in body["content"]


def test_acl_fields_plaintext_and_catalog_import_are_refused(
    registry_server, tmp_path: Path
) -> None:
    state = registry_server["state"]
    owner = RegistryClient(registry_server["url"], token=registry_server["token"])
    archive = _archive(tmp_path, name="clean.tar.gz")
    digest = sha256_file(archive)
    meta = {
        "kind": "snapshot-share",
        "suite_run_id": "suite0001",
        "dataset_id": "acme/demo",
        "dataset_version": "0.1.0",
        "blob_digest": digest,
        "size": archive.stat().st_size,
        "visibility": "public",
        "board_listed": True,
    }
    with pytest.raises(RegistryError) as blocked:
        owner._put_multipart(
            "/v1/shares",
            meta=meta,
            archive=archive,
            filename="snapshot.tar.gz",
            boundary_prefix="ageval-share",
        )
    assert blocked.value.code == "invalid_request"
    assert _count(state, "suite_results") == 0
    assert _count(state, "snapshot_shares") == 0

    secret = _archive(tmp_path, api_key="sk-supersecretvalue", name="secret.tar.gz")
    with pytest.raises(RegistryError) as leaked:
        _upload(owner, secret)
    assert leaked.value.code == "secret_scan_failed"
    assert _count(state, "snapshot_shares") == 0

    created = _upload(owner, archive)
    with pytest.raises(RegistryError) as imported:
        owner.upload_suite(
            suite_run_id="suite0001",
            dataset_id="acme/demo",
            dataset_version="0.1.0",
            visibility="private",
            pass_rate=1.0,
            mean_score=1.0,
            metrics={"pass_rate": 1.0},
            task_refs=[],
            agent_label="",
            model_label="",
            exit_code=0,
            blob_digest=digest,
            size=archive.stat().st_size,
            archive=archive,
        )
    assert imported.value.code == "share_not_importable"
    assert _count(state, "suite_results") == 0

    with pytest.raises(RegistryError) as listed:
        body = json.dumps({"kind": "leaderboard_list", "suite_run_id": created["token"]}).encode()
        owner._request(
            "POST",
            "/v1/requests",
            body=body,
            headers=owner._headers(content_type="application/json"),
        )
    assert listed.value.code == "share_not_listable"


def test_revoke_is_owner_only_and_drops_the_blob(registry_server, tmp_path: Path) -> None:
    state = registry_server["state"]
    owner = RegistryClient(registry_server["url"], token=registry_server["token"])
    created = _upload(owner, _archive(tmp_path))
    token = created["token"]
    digest = created["blob_digest"]
    mallory = RegistryClient(registry_server["url"], token="mallory-token")
    with pytest.raises(RegistryError) as denied:
        mallory.delete_snapshot_share(token)
    assert denied.value.code == "forbidden"
    anon = RegistryClient(registry_server["url"], token=None)
    assert anon.get_snapshot_share(token)["token"] == token

    assert owner.delete_snapshot_share(token)["ok"] is True
    assert state.blobs.open(digest, prefix="shares") is None
    assert _count(state, "snapshot_shares") == 0
    with pytest.raises(RegistryError) as missing:
        anon.get_snapshot_share(token)
    assert missing.value.code == "not_found"


def test_oversize_share_matches_suite_upload_error(registry_server) -> None:
    state = registry_server["state"]
    state.max_upload = 64
    url = registry_server["url"]

    def _post(path: str) -> tuple[int, str]:
        import urllib.error
        import urllib.request

        body = b"x" * 80
        req = urllib.request.Request(
            f"{url}{path}",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer owner-token",
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(body)),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                return int(resp.status), resp.read().decode()
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read().decode()

    share_status, share_body = _post("/v1/shares")
    suite_status, suite_body = _post("/v1/results/suites")
    assert share_status == suite_status == 413
    share_err = json.loads(share_body)
    suite_err = json.loads(suite_body)
    assert share_err["error"] == suite_err["error"] == "payload_too_large"
    assert share_err["message"] == suite_err["message"]


def _upload_live(client: RegistryClient, archive: Path) -> dict:
    return client.create_snapshot_share(
        suite_run_id="suite0001",
        dataset_id="acme/demo",
        dataset_version="0.1.0",
        blob_digest=sha256_file(archive),
        size=archive.stat().st_size,
        archive=archive,
        mode="live",
    )


def test_static_share_is_immutable(registry_server, tmp_path: Path) -> None:
    owner = RegistryClient(registry_server["url"], token=registry_server["token"])
    created = _upload(owner, _archive(tmp_path))
    assert created["mode"] == "static"
    state = registry_server["state"]
    assert _count(state, "snapshot_share_files") == 0
    with pytest.raises(RegistryError) as denied:
        owner.patch_snapshot_share(created["token"], summary=_summary())
    assert denied.value.code == "invalid_request"


def test_live_patch_keeps_the_token_and_serves_the_last_summary(
    registry_server, tmp_path: Path
) -> None:
    state = registry_server["state"]
    owner = RegistryClient(registry_server["url"], token=registry_server["token"])
    created = _upload_live(owner, _archive(tmp_path))
    token = created["token"]
    assert created["mode"] == "live"
    assert created["path"] == f"/s/{token}"
    assert _count(state, "suite_results") == 0
    assert _count(state, "result_shares") == 0
    assert _count(state, "snapshot_share_files") >= 1

    anon = RegistryClient(registry_server["url"], token=None)
    first = anon.get_snapshot_share(token)
    assert first["task_refs"][0]["status"] == "PASS"
    assert first["task_refs"][0]["has_attempt_content"] is True
    file_body = anon._request(
        "GET",
        f"/v1/shares/{token}/attempts/run000001/files/.ageval/runs/run000001/result.json",
        auth=False,
    )[1].decode()
    assert "PASS" in file_body

    running = _summary()
    running["status"] = "running"
    running["task_refs"] = [
        {"task_id": "hello", "status": "PASS", "score": 1, "run_id": "run000001"},
        {"task_id": "next", "status": "FAIL", "score": 0, "run_id": "run000002"},
    ]
    running["progress"] = {"done": 1, "total": 2, "status": "running", "running": 1}
    patched = owner.patch_snapshot_share(token, summary=running, heartbeat=True)
    assert patched["token"] == token
    mid = anon.get_snapshot_share(token)
    assert mid["token"] == token
    assert [item["task_id"] for item in mid["task_refs"]] == ["hello", "next"]
    assert mid["status"] == "running"
    assert mid["progress"]["running"] == 1
    assert mid["task_refs"][1]["has_attempt_content"] is False

    # Runner offline: the link stays on this patch until the next one.
    assert anon.get_snapshot_share(token)["status"] == "running"

    done = dict(running)
    done["status"] = "complete"
    done["progress"] = {"done": 2, "total": 2, "status": "complete", "running": 0}
    again = owner.patch_snapshot_share(token, summary=done)
    assert again["token"] == token
    assert anon.get_snapshot_share(token)["status"] == "complete"


def test_live_patch_scrubs_files_and_rejects_non_owners(registry_server, tmp_path: Path) -> None:
    state = registry_server["state"]
    owner = RegistryClient(registry_server["url"], token=registry_server["token"])
    created = _upload_live(owner, _archive(tmp_path, name="live.tar.gz"))
    token = created["token"]
    secret_summary = _summary(api_key="sk-supersecretvalue")
    secret_summary["visibility"] = "public"
    with pytest.raises(RegistryError) as acl:
        owner.patch_snapshot_share(token, summary=secret_summary)
    assert acl.value.code == "invalid_request"

    secret_summary.pop("visibility")
    patched = owner.patch_snapshot_share(token, summary=secret_summary)
    assert patched["job_overlay"]["solver"]["api_key"] == "[redacted]"
    anon = RegistryClient(registry_server["url"], token=None)
    assert "sk-supersecretvalue" not in json.dumps(anon.get_snapshot_share(token))

    patch_archive = tmp_path / "patch.tar.gz"
    patch_archive.write_bytes(
        _gzip_tar(
            {
                ".ageval/runs/run000002/result.json": (
                    b'{"status":"FAIL","score":0,"api_key":"sk-supersecretvalue"}\n'
                ),
            }
        )
    )
    advanced = _summary()
    advanced["task_refs"] = [
        {"task_id": "hello", "status": "PASS", "score": 1, "run_id": "run000001"},
        {"task_id": "next", "status": "FAIL", "score": 0, "run_id": "run000002"},
    ]
    owner.patch_snapshot_share(token, summary=advanced, archive=patch_archive)
    view = anon.get_snapshot_share(token)
    fail_ref = next(item for item in view["task_refs"] if item["task_id"] == "next")
    assert fail_ref["has_attempt_content"] is True
    stored = anon._request(
        "GET",
        f"/v1/shares/{token}/attempts/run000002/files/.ageval/runs/run000002/result.json",
        auth=False,
    )[1].decode()
    assert "sk-supersecretvalue" not in stored
    assert "[redacted]" in stored

    key_archive = tmp_path / "key.tar.gz"
    key_archive.write_bytes(_gzip_tar({"notes.txt": b"-----BEGIN PRIVATE KEY-----\nabc\n"}))
    with pytest.raises(RegistryError) as leaked:
        owner.patch_snapshot_share(token, summary=advanced, archive=key_archive)
    assert leaked.value.code == "secret_scan_failed"

    mallory = RegistryClient(registry_server["url"], token="mallory-token")
    with pytest.raises(RegistryError) as denied:
        mallory.patch_snapshot_share(token, summary=_summary())
    assert denied.value.code == "forbidden"
    anon_writer = RegistryClient(registry_server["url"], token=None)
    with pytest.raises(RegistryError) as unsigned:
        anon_writer.patch_snapshot_share(token, summary=_summary())
    assert unsigned.value.status == 401

    ceiling = state.shares.max_upload
    state.shares.max_upload = int(anon.get_snapshot_share(token)["size"])
    extra = tmp_path / "extra.tar.gz"
    extra.write_bytes(_gzip_tar({".ageval/runs/run000002/note.txt": b"more-evidence\n"}))
    with pytest.raises(RegistryError) as too_big:
        owner.patch_snapshot_share(token, summary=advanced, archive=extra)
    assert too_big.value.code == "payload_too_large"
    state.shares.max_upload = ceiling

    digests: list[str] = []
    with state.stores.results._connect() as conn:
        found = state.stores.results._exec(
            conn, "SELECT blob_digest FROM snapshot_share_files WHERE token=?", (token,)
        ).fetchall()
        digests = [str(row["blob_digest"]) for row in found]
    assert digests
    assert owner.delete_snapshot_share(token)["ok"] is True
    assert _count(state, "snapshot_shares") == 0
    assert _count(state, "snapshot_share_files") == 0
    for digest in digests:
        assert state.blobs.open(digest, prefix="shares") is None
    with pytest.raises(RegistryError) as missing:
        anon.get_snapshot_share(token)
    assert missing.value.code == "not_found"


def test_create_requires_upload_scope(registry_server, tmp_path: Path) -> None:
    anon = RegistryClient(registry_server["url"], token=None)
    with pytest.raises(RegistryError) as denied:
        _upload(anon, _archive(tmp_path))
    assert denied.value.status == 401
