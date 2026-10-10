"""Hosted org secrets, the e2b/daytona queue, and HTTP."""

from __future__ import annotations

import base64
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from services.registry.access import AccessPolicy
from services.registry.app import build_default_state, make_handler
from services.registry.auth.tokens import TokenInfo
from services.registry.clock import now
from services.registry.db.schema import open_sqlite_stores
from services.registry.errors import RegistryAppError
from services.registry.hosted.crypto import decrypt, encrypt
from services.registry.hosted.rows import JobRow
from services.registry.hosted.service import HostedService
from services.registry.packages.rows import ReleaseRow

from ageval.registry.media_types import DATASET_MEDIA_TYPE, PLUGIN_MEDIA_TYPE

_MASTER = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")


def _master(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGEVAL_HOSTED_SECRET_KEY", _MASTER)


def _svc(tmp_path: Path) -> tuple[HostedService, Any]:
    stores = open_sqlite_stores(tmp_path / "meta.sqlite3")
    access = AccessPolicy(orgs=stores.orgs, packages=stores.packages, results=stores.results)
    stores.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    svc = HostedService(stores.hosted, stores.orgs, stores.packages, access)
    return svc, stores


def _alice() -> TokenInfo:
    return TokenInfo(
        scopes=frozenset({"registry:publish", "results:upload", "results:read"}),
        user_id="alice",
    )


def _bob() -> TokenInfo:
    return TokenInfo(scopes=frozenset({"results:read"}), user_id="bob")


def _release(stores: Any, *, visibility: str = "public", media: str = DATASET_MEDIA_TYPE) -> None:
    stores.packages.insert(
        ReleaseRow(
            dataset_id="acme/demo",
            version="1",
            visibility=visibility,
            package_digest="sha256:" + "ab" * 32,
            blob_digest="sha256:" + "cd" * 32,
            size=4,
            media_type=media,
            created_at=now(),
            org_id="acme",
            uploaded_by="alice",
        )
    )


def _secret(svc: HostedService, *, name: str, kind: str, value: str, **extra: str) -> dict:
    return svc.create_secret(
        org_id="acme",
        name=name,
        kind=kind,
        value=value,
        locator=extra.get("locator", "OPENAI_API_KEY"),
        provider=extra.get("provider", ""),
        auth=_alice(),
    )


def _job(svc: HostedService, model_id: str, provider_id: str, **over: object) -> dict:
    body = {
        "org_id": "acme",
        "dataset_id": "acme/demo",
        "version": "1",
        "environment": "e2b",
        "model": "gpt-4.1",
        "model_secret_id": model_id,
        "provider_secret_id": provider_id,
        "agent_ref": "",
        "task_id": "",
        "max_concurrent_tasks": 1,
    }
    body.update(over)
    return svc.create_job(auth=_alice(), **body)  # type: ignore[arg-type]


def test_secret_roundtrip_hides_plaintext(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _master(monkeypatch)
    svc, stores = _svc(tmp_path)
    created = _secret(svc, name="openai", kind="model", value="sk-live")
    assert "ciphertext" not in created
    assert "sk-live" not in json.dumps(created)
    assert created["locator"] == "OPENAI_API_KEY"
    listed = svc.list_secrets(org_id="acme", auth=_alice())
    assert listed["items"][0]["secret_id"] == created["secret_id"]
    assert "sk-live" not in json.dumps(listed)
    monkeypatch.delenv("AGEVAL_HOSTED_SECRET_KEY", raising=False)
    still = svc.list_secrets(org_id="acme", auth=_alice())
    assert still["items"][0]["name"] == "openai"
    row = stores.hosted.get_secret(created["secret_id"])
    assert row is not None
    monkeypatch.setenv("AGEVAL_HOSTED_SECRET_KEY", _MASTER)
    assert decrypt(row.ciphertext) == "sk-live"


def test_duplicate_secret_name_conflicts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _master(monkeypatch)
    svc, _stores = _svc(tmp_path)
    _secret(svc, name="openai", kind="model", value="sk-live")
    with pytest.raises(RegistryAppError) as ei:
        _secret(svc, name="openai", kind="model", value="sk-other")
    assert ei.value.http_status == 409
    assert ei.value.error == "conflict"


def test_provider_locator_is_fixed_and_model_locator_is_reserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _master(monkeypatch)
    svc, _stores = _svc(tmp_path)
    created = svc.create_secret(
        org_id="acme",
        name="e2b",
        kind="provider",
        value="e2b-secret",
        locator="",
        provider="e2b",
        auth=_alice(),
    )
    assert created["locator"] == "E2B_API_KEY"
    assert created["provider"] == "e2b"
    with pytest.raises(RegistryAppError) as mismatch:
        svc.create_secret(
            org_id="acme",
            name="e2b-bad",
            kind="provider",
            value="e2b-secret",
            locator="OPENAI_API_KEY",
            provider="e2b",
            auth=_alice(),
        )
    assert mismatch.value.http_status == 400
    with pytest.raises(RegistryAppError) as reserved:
        _secret(svc, name="bad-model", kind="model", value="sk", locator="E2B_API_KEY")
    assert reserved.value.http_status == 400


def test_outsider_secret_is_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _master(monkeypatch)
    svc, _stores = _svc(tmp_path)
    with pytest.raises(RegistryAppError) as ei:
        svc.list_secrets(org_id="acme", auth=_bob())
    assert ei.value.http_status == 404


def test_enqueue_list_and_cancel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _master(monkeypatch)
    svc, stores = _svc(tmp_path)
    _release(stores)
    model = _secret(svc, name="openai", kind="model", value="sk-live")
    provider = _secret(
        svc, name="e2b", kind="provider", value="e2b-secret", locator="", provider="e2b"
    )
    queued = _job(svc, model["secret_id"], provider["secret_id"])
    assert queued["status"] == "queued"
    assert "sk-live" not in json.dumps(queued)
    assert "e2b-secret" not in json.dumps(queued)
    listed = svc.list_jobs(auth=_alice(), org_id="acme", dataset_id="acme/demo")
    assert [item["job_id"] for item in listed["items"]] == [queued["job_id"]]
    with pytest.raises(RegistryAppError) as outsider:
        svc.list_jobs(auth=_bob(), org_id="acme", dataset_id="")
    assert outsider.value.http_status == 404
    with pytest.raises(RegistryAppError) as hidden:
        svc.get_job(job_id=queued["job_id"], auth=_bob())
    assert hidden.value.http_status == 404
    canceled = svc.cancel_job(job_id=queued["job_id"], auth=_alice())
    assert canceled["status"] == "canceled"
    again = svc.cancel_job(job_id=queued["job_id"], auth=_alice())
    assert again["status"] == "canceled"


def test_docker_environment_and_bad_concurrency_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _master(monkeypatch)
    svc, stores = _svc(tmp_path)
    _release(stores)
    model = _secret(svc, name="openai", kind="model", value="sk-live")
    provider = _secret(
        svc, name="e2b", kind="provider", value="e2b-secret", locator="", provider="e2b"
    )
    with pytest.raises(RegistryAppError) as refused:
        _job(
            svc,
            model["secret_id"],
            provider["secret_id"],
            environment="docker",
        )
    assert refused.value.error == "hosted_environment_refused"
    assert refused.value.http_status == 400
    with pytest.raises(RegistryAppError) as boolean:
        _job(
            svc,
            model["secret_id"],
            provider["secret_id"],
            max_concurrent_tasks=True,
        )
    assert boolean.value.http_status == 400


def test_private_and_non_dataset_are_not_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _master(monkeypatch)
    svc, stores = _svc(tmp_path)
    _release(stores, visibility="private")
    model = _secret(svc, name="openai", kind="model", value="sk-live")
    provider = _secret(
        svc, name="e2b", kind="provider", value="e2b-secret", locator="", provider="e2b"
    )
    with pytest.raises(RegistryAppError) as hidden:
        svc.create_job(
            org_id="acme",
            dataset_id="acme/demo",
            version="1",
            environment="e2b",
            model="gpt-4.1",
            model_secret_id=model["secret_id"],
            provider_secret_id=provider["secret_id"],
            agent_ref="",
            task_id="",
            max_concurrent_tasks=1,
            auth=_bob(),
        )
    assert hidden.value.http_status == 404
    stores.packages.insert(
        ReleaseRow(
            dataset_id="acme/plug",
            version="1",
            visibility="public",
            package_digest="sha256:" + "ef" * 32,
            blob_digest="sha256:" + "11" * 32,
            size=4,
            media_type=PLUGIN_MEDIA_TYPE,
            created_at=now(),
            org_id="acme",
            uploaded_by="alice",
        )
    )
    with pytest.raises(RegistryAppError) as kind:
        _job(
            svc,
            model["secret_id"],
            provider["secret_id"],
            dataset_id="acme/plug",
        )
    assert kind.value.http_status == 400


def test_claim_is_fifo_and_stale_requeue(tmp_path: Path) -> None:
    stores = open_sqlite_stores(tmp_path / "meta.sqlite3")

    def put(job_id: str, created: float) -> None:
        row = JobRow(
            job_id=job_id,
            org_id="acme",
            dataset_id="acme/demo",
            version="1",
            environment="e2b",
            agent_ref="",
            model="gpt-4.1",
            model_secret_id="m",
            provider_secret_id="p",
            max_concurrent_tasks=1,
            task_id="",
            status="queued",
            error_title="",
            error_message="",
            suite_run_id="",
            created_by="alice",
            created_at=created,
            started_at=None,
            finished_at=None,
            worker_id="",
            cancel_requested=False,
        )
        stores.hosted.insert_job(row)

    put("old", 10)
    put("new", 20)
    first = stores.hosted.claim_next(worker_id="w1")
    assert first is not None
    assert first.job_id == "old"
    assert first.status == "running"
    second = stores.hosted.claim_next(worker_id="w2")
    assert second is not None
    assert second.job_id == "new"
    assert stores.hosted.claim_next(worker_id="w3") is None
    stale = JobRow(
        job_id="stuck",
        org_id="acme",
        dataset_id="acme/demo",
        version="1",
        environment="daytona",
        agent_ref="",
        model="gpt-4.1",
        model_secret_id="m",
        provider_secret_id="p",
        max_concurrent_tasks=1,
        task_id="",
        status="running",
        error_title="",
        error_message="",
        suite_run_id="",
        created_by="alice",
        created_at=1,
        started_at=1,
        finished_at=None,
        worker_id="dead",
        cancel_requested=False,
    )
    stores.hosted.insert_job(stale)
    assert stores.hosted.requeue_stale(100) == 1
    again = stores.hosted.claim_next(worker_id="w4")
    assert again is not None
    assert again.job_id == "stuck"
    stores.hosted.mark_cancel_requested("stuck")
    assert stores.hosted.cancel_stale(now() + 10, finished_at=50) == 1
    canceled = stores.hosted.get_job("stuck")
    assert canceled is not None
    assert canceled.status == "canceled"


def test_ciphertext_tamper_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGEVAL_HOSTED_SECRET_KEY", _MASTER)
    token = encrypt("sk-live")
    raw = bytearray(base64.urlsafe_b64decode(token))
    raw[20] ^= 1
    bad = base64.urlsafe_b64encode(bytes(raw)).decode("ascii")
    with pytest.raises(RegistryAppError) as ei:
        decrypt(bad)
    assert ei.value.error == "hosted_secret_corrupt"
    monkeypatch.delenv("AGEVAL_HOSTED_SECRET_KEY", raising=False)
    with pytest.raises(RegistryAppError) as missing:
        encrypt("sk-live")
    assert missing.value.error == "hosted_secret_key_missing"


def test_bootstrap_token_is_optional(tmp_path: Path) -> None:
    state, token = build_default_state(
        tmp_path / "reg",
        bootstrap_token="not-minted",
        memory_blob=True,
        mint_bootstrap=False,
    )
    assert state.auth.auth_for(token).user_id is None
    assert "admin" not in state.auth.auth_for(token).scopes


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGEVAL_HOSTED_SECRET_KEY", _MASTER)
    state, token = build_default_state(
        tmp_path / "reg", bootstrap_token="boot-token", memory_blob=True
    )
    state.stores.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    _release(state.stores)
    state.tokens.add(
        "tok-alice",
        frozenset({"results:upload", "registry:publish"}),
        github_user="alice",
    )
    state.tokens.add("tok-bob", frozenset({"results:read"}), github_user="bob")
    handler = make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield url
    server.shutdown()


def _call(url: str, token: str, method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_secret_and_job(api: str) -> None:
    status, secret = _call(
        api,
        "tok-alice",
        "POST",
        "/v1/orgs/acme/secrets",
        {"name": "openai", "kind": "model", "value": "sk-live", "locator": "OPENAI_API_KEY"},
    )
    assert status == 201
    assert "sk-live" not in json.dumps(secret)
    assert "ciphertext" not in secret
    status, provider = _call(
        api,
        "tok-alice",
        "POST",
        "/v1/orgs/acme/secrets",
        {"name": "e2b", "kind": "provider", "value": "e2b-secret", "provider": "e2b"},
    )
    assert status == 201
    assert provider["locator"] == "E2B_API_KEY"
    status, dup = _call(
        api,
        "tok-alice",
        "POST",
        "/v1/orgs/acme/secrets",
        {"name": "openai", "kind": "model", "value": "other", "locator": "OPENAI_API_KEY"},
    )
    assert status == 409
    status, outsider = _call(api, "tok-bob", "GET", "/v1/orgs/acme/secrets")
    assert status == 404
    status, unknown = _call(
        api,
        "tok-alice",
        "POST",
        "/v1/orgs/acme/secrets",
        {"name": "x", "kind": "model", "value": "v", "locator": "OPENAI_API_KEY", "extra": 1},
    )
    assert status == 400
    status, reserved = _call(
        api,
        "tok-alice",
        "POST",
        "/v1/orgs/acme/secrets",
        {"name": "bad", "kind": "model", "value": "v", "locator": "E2B_API_KEY"},
    )
    assert status == 400
    status, job = _call(
        api,
        "tok-alice",
        "POST",
        "/v1/hosted/jobs",
        {
            "org_id": "acme",
            "dataset_id": "acme/demo",
            "version": "1",
            "environment": "e2b",
            "model": "gpt-4.1",
            "model_secret_id": secret["secret_id"],
            "provider_secret_id": provider["secret_id"],
        },
    )
    assert status == 201
    assert job["status"] == "queued"
    status, docker = _call(
        api,
        "tok-alice",
        "POST",
        "/v1/hosted/jobs",
        {
            "org_id": "acme",
            "dataset_id": "acme/demo",
            "version": "1",
            "environment": "docker",
            "model": "gpt-4.1",
            "model_secret_id": secret["secret_id"],
            "provider_secret_id": provider["secret_id"],
        },
    )
    assert status == 400
    assert docker["error"] == "hosted_environment_refused"
    status, hidden = _call(api, "tok-bob", "GET", f"/v1/hosted/jobs/{job['job_id']}")
    assert status == 404
    status, canceled = _call(api, "tok-alice", "POST", f"/v1/hosted/jobs/{job['job_id']}/cancel")
    assert status == 200
    assert canceled["status"] == "canceled"
