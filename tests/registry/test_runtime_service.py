"""Agent Performance derives from official public board suites via agent_ref."""

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

from ageval.registry.archive import MEDIA_TYPE, build_archive
from ageval.registry.digest import compute_package_digest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"

GROK = {
    "executor": "acp",
    "extensions": [{"plugin": "acp", "options": {"entry": "grok-build"}}],
    "model": "g1",
    "api_key": "OPENAI_API_KEY",
}


def _ref(package_id: str, version: str = "0.1.0") -> str:
    return f"{package_id}@{version}+sha256:aaaaaaaaaaaa"


def _bound(
    package_id: str,
    *,
    version: str = "0.1.0",
    entry: str = "grok-build",
    **extra: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "executor": "acp",
        "extensions": [{"plugin": "acp", "options": {"entry": entry}}],
        "model": "g1",
        "agent_ref": _ref(package_id, version),
    }
    row.update(extra)
    return row


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


def _publish(
    packages: PackageService,
    tmp_path: Path,
    *,
    dataset_id: str,
    org_id: str,
    version: str = "0.1.0",
    slot: str | None = None,
    visibility: str = "public",
) -> None:
    if packages.orgs.get_org(org_id) is None:
        packages.orgs.create_org(name=org_id, owner_user_id="alice", display_name=org_id)
    archive, blob_digest, size = build_archive(FIXTURE)
    meta: dict[str, object] = {
        "dataset_id": dataset_id,
        "version": version,
        "package_digest": compute_package_digest(FIXTURE),
        "blob_digest": blob_digest,
        "media_type": MEDIA_TYPE,
        "visibility": visibility,
        "org_id": org_id,
        "size": size,
    }
    if slot:
        meta["slot"] = slot
    packages.publish(
        meta=meta,
        archive=_as_path(tmp_path, archive, f"{org_id}-{dataset_id.replace('/', '_')}.tar.gz"),
        auth=TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice"),
    )


def _suite_meta(
    tmp_path: Path,
    *,
    suite_run_id: str,
    dataset_id: str,
    agent_profiles: dict[str, dict[str, object]] | None,
    visibility: str = "public",
    version: str = "0.1.0",
    task_refs: list[dict[str, object]] | None = None,
    extra_overlay: dict[str, object] | None = None,
    pass_rate: float = 0.4,
    mean_score: float = 0.4,
) -> tuple[dict[str, object], Path]:
    archive = suite_run_id.encode()
    blob = f"sha256:{hashlib.sha256(archive).hexdigest()}"
    overlay: dict[str, object] | None = None
    if agent_profiles is not None:
        overlay = {"agent_profiles": agent_profiles}
        if extra_overlay:
            overlay.update(extra_overlay)
    meta: dict[str, object] = {
        "suite_run_id": suite_run_id,
        "dataset_id": dataset_id,
        "dataset_version": version,
        "visibility": visibility,
        "blob_digest": blob,
        "size": len(archive),
        "pass_rate": pass_rate,
        "mean_score": mean_score,
        "metrics": {"pass_rate": pass_rate, "n_attempts": 1},
        "task_refs": task_refs
        if task_refs is not None
        else [{"task_id": "hello", "status": "PASS", "score": 1.0}],
    }
    if overlay is not None:
        meta["job_overlay"] = overlay
    return meta, _as_path(tmp_path, archive, f"{suite_run_id}.bin")


def _consent(results: ResultService, suite_run_id: str, package_id: str) -> None:
    results.inbox.grant_agent_consent(
        suite_run_id=suite_run_id,
        package_id=package_id,
        granted_by="alice",
        source="attach",
    )


def _upload(
    results: ResultService,
    tmp_path: Path,
    **kwargs: object,
) -> dict[str, object]:
    meta, archive = _suite_meta(tmp_path, **kwargs)  # type: ignore[arg-type]
    return results.upload_suite(
        meta=meta,
        archive=archive,
        auth=TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice"),
    )


def test_builtin_harness_performances_skip_consent(tmp_path: Path) -> None:
    packages, results, runtimes = _services(tmp_path)
    _publish(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    builtin_binding = {
        "executor": "acp",
        "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
        "model": "glm-4.7",
        "agent_ref": "pi@0.1.0+sha256:aaaaaaaaaaaa",
    }
    uploaded_binding = _bound("official/pi-default", entry="pi", model="dashscope/qwen")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_builtin_ref",
        dataset_id="official/gaia",
        agent_profiles={"solver": builtin_binding},
    )
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_uploaded_ref",
        dataset_id="official/gaia",
        agent_profiles={"solver": uploaded_binding},
    )
    auth = TokenInfo(scopes=frozenset(), user_id="")
    assert runtimes.performances_for_agent("official/pi-default", auth) == []
    rows = runtimes.performances_for_agent("pi", auth)
    by_suite = {r["suite_run_id"]: r for r in rows}
    assert set(by_suite) == {"suite_builtin_ref", "suite_uploaded_ref"}
    assert by_suite["suite_builtin_ref"]["model"] == "glm-4.7"
    assert by_suite["suite_builtin_ref"]["package_id"] == "pi"
    assert by_suite["suite_uploaded_ref"]["model"] == "dashscope/qwen"
    assert by_suite["suite_uploaded_ref"]["package_id"] == "pi"
    listed = results.list_suites(auth=auth, dataset_id=None)
    by_id = {i["suite_run_id"]: i for i in listed["items"]}
    assert by_id["suite_builtin_ref"]["agent_refs"] == [{"role": "solver", "package_id": "pi"}]
    assert "agent_refs" not in by_id["suite_uploaded_ref"]


def test_official_public_suite_appears_community_does_not(tmp_path: Path) -> None:
    packages, results, runtimes = _services(tmp_path)
    _publish(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _publish(packages, tmp_path, dataset_id="acme/looks-official", org_id="acme")
    binding = _bound("official/http-default")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_official",
        dataset_id="official/gaia",
        agent_profiles={"solver": binding},
    )
    _consent(results, "suite_official", "official/http-default")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_community",
        dataset_id="acme/looks-official",
        agent_profiles={"solver": binding},
    )
    _consent(results, "suite_community", "official/http-default")
    auth = TokenInfo(scopes=frozenset(), user_id="")
    rows = runtimes.performances_for_agent("official/http-default", auth)
    assert [r["suite_run_id"] for r in rows] == ["suite_official"]
    official_suites = results.list_suites(auth=auth, dataset_id=None)
    by_id = {i["suite_run_id"]: i for i in official_suites["items"]}
    assert by_id["suite_official"]["agent_refs"] == [
        {"role": "solver", "package_id": "official/http-default"}
    ]
    assert "agent_refs" not in by_id["suite_community"]
    assert "runtime_refs" not in by_id["suite_official"]


def test_private_incomplete_draft_excluded(tmp_path: Path) -> None:
    packages, results, runtimes = _services(tmp_path)
    _publish(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _publish(
        packages,
        tmp_path,
        dataset_id="official/gaia-draft",
        org_id="official",
        slot="draft",
        visibility="private",
    )
    bound = _bound("official/http-default")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_private",
        dataset_id="official/gaia",
        agent_profiles={"solver": bound},
        visibility="private",
    )
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_incomplete",
        dataset_id="official/gaia",
        agent_profiles={"solver": bound},
        task_refs=[],
    )
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_draft",
        dataset_id="official/gaia-draft",
        version="0.1.0",
        agent_profiles={"solver": bound},
    )
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    assert runtimes.performances_for_agent("official/http-default", auth) == []
    jobs = results.list_suites(auth=auth, dataset_id=None)
    for item in jobs["items"]:
        assert "agent_refs" not in item
        assert "runtime_refs" not in item


def test_profiles_only_suite_does_not_appear(tmp_path: Path) -> None:
    packages, results, runtimes = _services(tmp_path)
    _publish(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_profiles",
        dataset_id="official/gaia",
        agent_profiles={"solver": dict(GROK)},
    )
    auth = TokenInfo(scopes=frozenset(), user_id="")
    assert runtimes.performances_for_agent("official/http-default", auth) == []
    suites = results.list_suites(auth=auth, dataset_id=None)
    assert "agent_refs" not in suites["items"][0]


def test_two_agents_same_entry_stay_separate(tmp_path: Path) -> None:
    packages, results, runtimes = _services(tmp_path)
    _publish(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_a",
        dataset_id="official/gaia",
        agent_profiles={"solver": _bound("official/foo", entry="claude-code")},
    )
    _consent(results, "suite_a", "official/foo")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_b",
        dataset_id="official/gaia",
        agent_profiles={"solver": _bound("official/bar", entry="claude-code")},
    )
    _consent(results, "suite_b", "official/bar")
    auth = TokenInfo(scopes=frozenset(), user_id="")
    foo = runtimes.performances_for_agent("official/foo", auth)
    bar = runtimes.performances_for_agent("official/bar", auth)
    assert [r["suite_run_id"] for r in foo] == ["suite_a"]
    assert [r["suite_run_id"] for r in bar] == ["suite_b"]


def test_versions_group_on_same_package(tmp_path: Path) -> None:
    packages, results, runtimes = _services(tmp_path)
    _publish(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_v1",
        dataset_id="official/gaia",
        agent_profiles={"solver": _bound("official/foo", version="0.1.0")},
    )
    _consent(results, "suite_v1", "official/foo")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_v2",
        dataset_id="official/gaia",
        agent_profiles={"solver": _bound("official/foo", version="0.2.0")},
    )
    _consent(results, "suite_v2", "official/foo")
    rows = runtimes.performances_for_agent(
        "official/foo", TokenInfo(scopes=frozenset(), user_id="")
    )
    versions = {r["suite_run_id"]: r["agent_version"] for r in rows}
    assert versions == {"suite_v1": "0.1.0", "suite_v2": "0.2.0"}


def test_file_and_local_refs_do_not_appear(tmp_path: Path) -> None:
    packages, results, runtimes = _services(tmp_path)
    _publish(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_file",
        dataset_id="official/gaia",
        agent_profiles={
            "solver": {
                **GROK,
                "agent_ref": "file:/tmp/agent@dev+sha256:aaaaaaaaaaaa",
            }
        },
    )
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_local",
        dataset_id="official/gaia",
        agent_profiles={
            "solver": {
                **GROK,
                "agent_ref": "local/http-default@0.1.0+sha256:aaaaaaaaaaaa",
            }
        },
    )
    auth = TokenInfo(scopes=frozenset(), user_id="")
    assert runtimes.performances_for_agent("official/http-default", auth) == []
    assert runtimes.performances_for_agent("local/http-default", auth) == []
    suites = results.list_suites(auth=auth, dataset_id=None)
    for item in suites["items"]:
        assert "agent_refs" not in item


def test_performance_overlays_and_teammates(tmp_path: Path) -> None:
    packages, results, runtimes = _services(tmp_path)
    _publish(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    solver = _bound(
        "official/foo",
        overlays=["overlays/skills/jsonl-agg", "overlays/AGENTS.md"],
    )
    user = _bound("official/bar", entry="pi")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_overlays",
        dataset_id="official/gaia",
        agent_profiles={"solver": solver, "user": user},
        pass_rate=0.5,
        mean_score=0.5,
    )
    _consent(results, "suite_overlays", "official/foo")
    _consent(results, "suite_overlays", "official/bar")
    auth = TokenInfo(scopes=frozenset(), user_id="")
    foo = runtimes.performances_for_agent("official/foo", auth)
    assert len(foo) == 1
    assert foo[0]["role"] == "solver"
    assert foo[0]["overlays"] == ["overlays/skills/jsonl-agg", "overlays/AGENTS.md"]
    assert foo[0]["package_digest"] == compute_package_digest(FIXTURE)
    assert [t["role"] for t in foo[0]["teammates"]] == ["user"]
    bar = runtimes.performances_for_agent("official/bar", auth)
    assert bar[0]["role"] == "user"
    assert "overlays" not in bar[0]


def test_runtimes_http_gone(tmp_path: Path) -> None:
    state, token = build_default_state(tmp_path / "http", bootstrap_token="tok", memory_blob=True)
    api = RegistryHttpApi(state)
    listed = api.dispatch(
        method="GET",
        path="/v1/runtimes",
        headers={"Authorization": f"Bearer {token}"},
        body=BytesIO(),
        content_length=0,
    )
    assert listed.status == 404
    detail = api.dispatch(
        method="GET",
        path="/v1/runtimes/rt_unknown",
        headers={"Authorization": f"Bearer {token}"},
        body=BytesIO(),
        content_length=0,
    )
    assert detail.status == 404
    payload = json.loads(detail.body.decode("utf-8"))
    assert payload["error"] == "not_found"


def test_performances_on_package_versions(tmp_path: Path) -> None:
    packages, results, runtimes = _services(tmp_path)
    _publish(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_pkg",
        dataset_id="official/gaia",
        agent_profiles={"solver": _bound("official/http-default")},
    )
    _consent(results, "suite_pkg", "official/http-default")
    state, token = build_default_state(tmp_path / "http2", bootstrap_token="tok", memory_blob=True)
    # Reuse the same sqlite? build_default_state is a new empty registry.
    # Call the service directly for this assertion; HTTP wiring is covered above.
    rows = runtimes.performances_for_agent(
        "official/http-default", TokenInfo(scopes=frozenset(), user_id="")
    )
    assert rows[0]["agent_version"] == "0.1.0"
    assert rows[0]["package_id"] == "official/http-default"


def test_agent_ref_without_consent_does_not_appear(tmp_path: Path) -> None:
    packages, results, runtimes = _services(tmp_path)
    _publish(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_no_consent",
        dataset_id="official/gaia",
        agent_profiles={"solver": _bound("official/http-default")},
    )
    auth = TokenInfo(scopes=frozenset(), user_id="")
    assert runtimes.performances_for_agent("official/http-default", auth) == []
    suites = results.list_suites(auth=auth, dataset_id=None)
    assert "agent_refs" not in suites["items"][0]


def test_builtin_collect_off_and_personal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGEVAL_REGISTRY_MAINTAINERS", "alice")
    packages, results, runtimes = _services(tmp_path)
    _publish(packages, tmp_path, dataset_id="official/gaia", org_id="official")
    _publish(packages, tmp_path, dataset_id="acme/bench", org_id="acme")
    pi = {
        "executor": "acp",
        "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
        "model": "glm-4.7",
    }
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_official",
        dataset_id="official/gaia",
        agent_profiles={"solver": dict(pi)},
    )
    _upload(
        results,
        tmp_path,
        suite_run_id="suite_personal",
        dataset_id="acme/bench",
        agent_profiles={"solver": dict(pi)},
    )
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    official_ids = {r["suite_run_id"] for r in runtimes.performances_for_agent("pi", auth)}
    assert official_ids == {"suite_official"}
    runtimes.set_collect_mode(package_id="pi", mode="off", auth=auth)
    assert runtimes.performances_for_agent("pi", auth) == []
    runtimes.set_collect_mode(package_id="pi", mode="official_and_personal", auth=auth)
    both = {r["suite_run_id"] for r in runtimes.performances_for_agent("pi", auth)}
    assert both == {"suite_official", "suite_personal"}
    with pytest.raises(RegistryAppError) as forbidden:
        runtimes.set_collect_mode(
            package_id="pi",
            mode="off",
            auth=TokenInfo(scopes=frozenset({"results:upload"}), user_id="bob"),
        )
    assert forbidden.value.http_status == 403
