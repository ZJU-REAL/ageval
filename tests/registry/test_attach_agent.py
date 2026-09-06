"""Delayed published agent_ref attach on stored suite overlay."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest
from services.registry.access import AccessPolicy
from services.registry.app import build_default_state
from services.registry.errors import RegistryAppError
from services.registry.http_api import RegistryHttpApi
from services.registry.package_service import PackageService
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


def _services(tmp_path: Path) -> tuple[PackageService, ResultService, RuntimeService]:
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
    return packages, results, RuntimeService(meta.inbox, meta.packages, results)


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
    visibility: str = "public",
) -> None:
    if packages.orgs.get_org(org_id) is None:
        packages.orgs.create_org(name=org_id, owner_user_id="alice", display_name=org_id)
    archive, blob_digest, size = build_archive(FIXTURE)
    packages.publish(
        meta={
            "dataset_id": dataset_id,
            "version": "0.1.0",
            "package_digest": compute_package_digest(FIXTURE),
            "blob_digest": blob_digest,
            "media_type": MEDIA_TYPE,
            "visibility": visibility,
            "org_id": org_id,
            "size": size,
            "package_kind": "dataset",
        },
        archive=_as_path(tmp_path, archive, f"{dataset_id.replace('/', '_')}.tar.gz"),
        auth=TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice"),
    )


def _publish_agent(
    packages: PackageService,
    tmp_path: Path,
    *,
    package_id: str,
    org_id: str,
) -> str:
    if packages.orgs.get_org(org_id) is None:
        packages.orgs.create_org(name=org_id, owner_user_id="alice", display_name=org_id)
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
        auth=TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice"),
    )
    return "0.1.0"


def _upload(
    results: ResultService,
    tmp_path: Path,
    *,
    suite_run_id: str,
    dataset_id: str,
    agent_profiles: dict[str, dict[str, object]],
    visibility: str = "public",
    fingerprint: str = "sha256:aaaaaaaa",
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
        "task_refs": [{"task_id": "hello", "status": "PASS", "score": 1.0}],
        "job_overlay": {"agent_profiles": agent_profiles},
        "config_fingerprint": fingerprint,
    }
    return results.upload_suite(
        meta=meta,
        archive=_as_path(tmp_path, archive, f"{suite_run_id}.bin"),
        auth=TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice"),
    )


def test_attach_builtin_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGEVAL_REGISTRY_MAINTAINERS", "alice")
    packages, results, runtimes = _services(tmp_path)
    _publish_dataset(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_builtin",
        dataset_id="official/gaia",
        agent_profiles={"solver": dict(PI)},
    )
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    attached = results.attach_agent(
        suite_run_id="suite_builtin",
        agent="pi",
        auth=auth,
    )
    assert attached["attached"] is True
    overlay = attached["job_overlay"]["agent_profiles"]["solver"]
    assert str(overlay["agent_ref"]).startswith("pi@0.1.0+")
    assert attached["agent_refs"] == [{"role": "solver", "package_id": "pi"}]
    rows = runtimes.performances_for_agent("pi", auth)
    assert [r["suite_run_id"] for r in rows] == ["suite_builtin"]
    again = results.attach_agent(
        suite_run_id="suite_builtin",
        agent="pi@0.1.0",
        auth=auth,
    )
    assert again["idempotent"] is True


def test_named_role_attach_skips_teammate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGEVAL_REGISTRY_MAINTAINERS", "alice")
    packages, results, runtimes = _services(tmp_path)
    _publish_dataset(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    http = {
        "executor": "openai-http",
        "extensions": [{"plugin": "openai-http"}, {"plugin": "local"}],
        "model": "dashscope/qwen3.8-max",
    }
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_dual",
        dataset_id="official/gaia",
        agent_profiles={
            "user": dict(http),
            "service": {**http, "model": "dashscope/deepseek-v4-pro"},
        },
    )
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    before = {
        (r["suite_run_id"], r["role"]) for r in runtimes.performances_for_agent("openai-http", auth)
    }
    assert before == {("suite_dual", "user"), ("suite_dual", "service")}
    attached = results.attach_agent(
        suite_run_id="suite_dual",
        agent="service=openai-http",
        auth=auth,
    )
    profiles = attached["job_overlay"]["agent_profiles"]
    assert "agent_ref" not in profiles["user"]
    assert str(profiles["service"]["agent_ref"]).startswith("openai-http@")
    after = {
        (r["suite_run_id"], r["role"]) for r in runtimes.performances_for_agent("openai-http", auth)
    }
    assert after == {("suite_dual", "service")}
    runtimes.detach_performance(
        package_id="openai-http",
        suite_run_id="suite_dual",
        role="service",
        auth=auth,
    )
    meta = results.serve_suite_meta(suite_run_id="suite_dual", auth=auth)
    assert "agent_ref" not in meta["job_overlay"]["agent_profiles"]["service"]
    assert "agent_ref" not in meta["job_overlay"]["agent_profiles"]["user"]
    after_remove = {
        (r["suite_run_id"], r["role"]) for r in runtimes.performances_for_agent("openai-http", auth)
    }
    assert after_remove == {("suite_dual", "user"), ("suite_dual", "service")}
    again = results.attach_agent(
        suite_run_id="suite_dual",
        agent="service=openai-http",
        auth=auth,
    )
    assert str(again["job_overlay"]["agent_profiles"]["service"]["agent_ref"]).startswith(
        "openai-http@"
    )
    after_reattach = {
        (r["suite_run_id"], r["role"]) for r in runtimes.performances_for_agent("openai-http", auth)
    }
    assert after_reattach == {("suite_dual", "service")}


def test_attach_builtin_without_maintainer_is_forbidden(tmp_path: Path) -> None:
    packages, results, _runtimes = _services(tmp_path)
    _publish_dataset(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_builtin",
        dataset_id="official/gaia",
        agent_profiles={"solver": dict(PI)},
    )
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    with pytest.raises(RegistryAppError) as forbidden:
        results.attach_agent(suite_run_id="suite_builtin", agent="pi", auth=auth)
    assert forbidden.value.http_status == 403


def test_attach_plaza_suite_then_performances(tmp_path: Path) -> None:
    packages, results, runtimes = _services(tmp_path)
    _publish_dataset(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _publish_agent(packages, tmp_path, package_id="official/pi-default", org_id="official")
    uploaded = _upload(
        results,
        tmp_path,
        suite_run_id="suite_profiles",
        dataset_id="official/gaia",
        agent_profiles={"solver": dict(PI)},
    )
    assert "agent_refs" not in uploaded
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    before = results.serve_suite_meta(suite_run_id="suite_profiles", auth=auth)
    assert runtimes.performances_for_agent("official/pi-default", auth) == []
    attached = results.attach_agent(
        suite_run_id="suite_profiles",
        agent="official/pi-default@0.1.0",
        auth=auth,
    )
    assert attached["attached"] is True
    assert attached["idempotent"] is False
    assert attached["config_fingerprint"] == before["config_fingerprint"]
    overlay = attached["job_overlay"]["agent_profiles"]["solver"]
    assert str(overlay["agent_ref"]).startswith("official/pi-default@0.1.0+")
    rows = runtimes.performances_for_agent("official/pi-default", auth)
    assert [r["suite_run_id"] for r in rows] == ["suite_profiles"]
    again = results.attach_agent(
        suite_run_id="suite_profiles",
        agent="official/pi-default@0.1.0",
        auth=auth,
    )
    assert again["idempotent"] is True
    assert again["config_fingerprint"] == before["config_fingerprint"]


def test_attach_private_suite_is_metadata_only(tmp_path: Path) -> None:
    packages, results, runtimes = _services(tmp_path)
    _publish_dataset(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _publish_agent(packages, tmp_path, package_id="official/pi-default", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_private",
        dataset_id="official/gaia",
        agent_profiles={"solver": dict(PI)},
        visibility="private",
    )
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    results.attach_agent(
        suite_run_id="suite_private",
        agent="official/pi-default@0.1.0",
        auth=auth,
    )
    assert runtimes.performances_for_agent("official/pi-default", auth) == []
    meta = results.serve_suite_meta(suite_run_id="suite_private", auth=auth)
    assert "agent_ref" in meta["job_overlay"]["agent_profiles"]["solver"]
    assert "agent_refs" not in meta


def test_attach_succeeds_when_only_model_differs(tmp_path: Path) -> None:
    packages, results, _runtimes = _services(tmp_path)
    _publish_dataset(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _publish_agent(packages, tmp_path, package_id="official/pi-default", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_model",
        dataset_id="official/gaia",
        agent_profiles={"solver": {**PI, "model": "glm-4.7"}},
    )
    owner = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    attached = results.attach_agent(
        suite_run_id="suite_model",
        agent="official/pi-default@0.1.0",
        auth=owner,
    )
    assert attached["attached"] is True
    overlay = attached["job_overlay"]["agent_profiles"]["solver"]
    assert overlay["model"] == "glm-4.7"
    assert str(overlay["agent_ref"]).startswith("official/pi-default@0.1.0+")


def test_attach_succeeds_when_only_plugin_options_differ(tmp_path: Path) -> None:
    packages, results, _runtimes = _services(tmp_path)
    _publish_dataset(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _publish_agent(packages, tmp_path, package_id="official/pi-default", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_effort",
        dataset_id="official/gaia",
        agent_profiles={
            "solver": {
                **PI,
                "extensions": [
                    {"plugin": "acp", "options": {"entry": "pi", "reasoning_effort": "max"}}
                ],
            }
        },
    )
    owner = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    attached = results.attach_agent(
        suite_run_id="suite_effort",
        agent="official/pi-default@0.1.0",
        auth=owner,
    )
    assert attached["attached"] is True
    overlay = attached["job_overlay"]["agent_profiles"]["solver"]
    assert overlay["extensions"][0]["options"]["reasoning_effort"] == "max"
    assert str(overlay["agent_ref"]).startswith("official/pi-default@0.1.0+")


def test_attach_mismatch_and_unauthorized(tmp_path: Path) -> None:
    packages, results, _runtimes = _services(tmp_path)
    _publish_dataset(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _publish_agent(packages, tmp_path, package_id="official/pi-default", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_mis",
        dataset_id="official/gaia",
        agent_profiles={
            "solver": {
                **PI,
                "extensions": [{"plugin": "acp", "options": {"entry": "codex"}}],
            }
        },
    )
    owner = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    with pytest.raises(RegistryAppError, match="does not match"):
        results.attach_agent(
            suite_run_id="suite_mis",
            agent="official/pi-default@0.1.0",
            role="solver",
            auth=owner,
        )
    meta = results.serve_suite_meta(suite_run_id="suite_mis", auth=owner)
    assert "agent_ref" not in meta["job_overlay"]["agent_profiles"]["solver"]
    with pytest.raises(RegistryAppError, match="published"):
        results.attach_agent(
            suite_run_id="suite_mis",
            agent="local/pi-default@0.1.0",
            auth=owner,
        )
    bob = TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob")
    with pytest.raises(RegistryAppError) as exc:
        results.attach_agent(
            suite_run_id="suite_mis",
            agent="official/pi-default@0.1.0",
            auth=bob,
        )
    assert exc.value.http_status == 404


def test_attach_http_roundtrip(tmp_path: Path) -> None:
    state, token = build_default_state(tmp_path / "http", bootstrap_token="tok", memory_blob=True)
    packages, results = state.packages, state.results
    _publish_dataset(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _publish_agent(packages, tmp_path, package_id="official/pi-default", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_http",
        dataset_id="official/gaia",
        agent_profiles={"solver": dict(PI)},
    )
    api = RegistryHttpApi(state)
    extra = json.dumps({"agent": "official/pi-default@0.1.0", "extra": 1}).encode()
    bad = api.dispatch(
        method="PATCH",
        path="/v1/results/suites/suite_http/agent-ref",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Content-Length": str(len(extra)),
        },
        body=BytesIO(extra),
        content_length=len(extra),
    )
    assert bad.status == 400
    body = json.dumps({"agent": "official/pi-default@0.1.0"}).encode()
    ok = api.dispatch(
        method="PATCH",
        path="/v1/results/suites/suite_http/agent-ref",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
        body=BytesIO(body),
        content_length=len(body),
    )
    assert ok.status == 200, ok.body.decode()
    payload = json.loads(ok.body.decode())
    assert payload["attached"] is True
    assert str(payload["job_overlay"]["agent_profiles"]["solver"]["agent_ref"]).startswith(
        "official/pi-default@0.1.0+"
    )
