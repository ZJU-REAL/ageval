"""Spec 04: publish plugin → preview → install to local cache."""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from services.registry.app import build_default_state, make_handler

from ageval.application.composition import build_plugin_commands
from ageval.registry.client import RegistryClient, RegistryError
from ageval.registry.credentials import write_credentials
from ageval.registry.plugin_package import PLUGIN_MEDIA_TYPE

_plugins = build_plugin_commands()
install_plugin_from_registry = _plugins.install_plugin_from_registry
publish_plugin = _plugins.publish_plugin

REPO = Path(__file__).resolve().parents[2]
PLUGIN_FIXTURE = REPO / "tests" / "fixtures" / "plugins" / "sample-echo"
TEST_ORG = "test"


@pytest.fixture()
def registry_server(tmp_path: Path):
    data = tmp_path / "reg-data"
    state, token = build_default_state(data, bootstrap_token="test-token-plugin", memory_blob=True)
    handler = make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    yield {"url": url, "token": token, "state": state}
    server.shutdown()


def _ensure_org(url: str, token: str) -> None:
    client = RegistryClient(url, token=token)
    try:
        client.create_org(name=TEST_ORG, display_name="Test Org")
    except RegistryError:
        return


def test_publish_plugin_preview_and_install(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    creds = tmp_path / "credentials"
    write_credentials(
        url=registry_server["url"],
        token=registry_server["token"],
        path=creds,
    )
    monkeypatch.setenv("AGEVAL_REGISTRY_URL", registry_server["url"])
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", registry_server["token"])
    home = tmp_path / "ageval-home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    from ageval.plugins import bootstrap as boot
    from ageval.plugins.registry import reset_global_registry

    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()

    _ensure_org(registry_server["url"], registry_server["token"])

    summary = publish_plugin(PLUGIN_FIXTURE, public=False, org=TEST_ORG)
    assert summary["ok"] is True
    assert summary["package_kind"] == "plugin"
    assert summary["media_type"] == PLUGIN_MEDIA_TYPE
    assert "executor" in summary["slots_summary"]["exclusive"]
    ref = summary["ref"]

    client = RegistryClient(registry_server["url"], token=registry_server["token"])
    meta = client.get_metadata(dataset_id=summary["package_id"], version=summary["version"])
    assert meta.media_type == PLUGIN_MEDIA_TYPE
    # Raw client returns ReleaseInfo; full preview via direct HTTP
    import json
    import urllib.request

    path = f"/v1/packages/{summary['package_id']}/versions/{summary['version']}"
    req = urllib.request.Request(
        registry_server["url"] + path,
        headers={"Authorization": f"Bearer {registry_server['token']}"},
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        body = json.loads(resp.read().decode("utf-8"))
    assert body.get("package_kind") == "plugin"
    assert body.get("plugin_preview", {}).get("description") == (
        "Fixture executor used by registry plugin publish tests."
    )
    assert body.get("plugin_preview", {}).get("slots", {}).get("exclusive") == ["executor"]
    declared = body.get("plugin_preview", {}).get("declared") or []
    ids = {d.get("id") for d in declared}
    assert "executor" in ids
    assert "before_agent_invoke" in ids
    exec_row = next(d for d in declared if d.get("id") == "executor")
    assert exec_row.get("kind") == "exclusive"
    assert "plugin.yaml" in body.get("plugin_preview", {}).get("files", [])

    # Spec 06: list exposes package_kind without opening blob; filter works.
    list_req = urllib.request.Request(
        registry_server["url"] + "/v1/packages?package_kind=plugin",
        headers={"Authorization": f"Bearer {registry_server['token']}"},
    )
    with urllib.request.urlopen(list_req) as resp:  # noqa: S310
        listed = json.loads(resp.read().decode("utf-8"))
    plugin_items = listed.get("items") or []
    assert any(i.get("dataset_id") == summary["package_id"] for i in plugin_items)
    assert all(i.get("package_kind") == "plugin" for i in plugin_items)
    echo_row = next(i for i in plugin_items if i.get("dataset_id") == summary["package_id"])
    assert echo_row.get("official") is False
    assert echo_row.get("org_id") == TEST_ORG
    assert echo_row.get("download_count") == 0
    db_req = urllib.request.Request(
        registry_server["url"] + "/v1/packages?package_kind=dataset",
        headers={"Authorization": f"Bearer {registry_server['token']}"},
    )
    with urllib.request.urlopen(db_req) as resp:  # noqa: S310
        db_listed = json.loads(resp.read().decode("utf-8"))
    assert not any(
        i.get("dataset_id") == summary["package_id"] for i in (db_listed.get("items") or [])
    )

    installed = install_plugin_from_registry(ref)
    assert installed["ok"] is True
    assert installed["plugin_id"] == f"{TEST_ORG}/sample-echo"
    with urllib.request.urlopen(list_req) as resp:  # noqa: S310
        listed_after = json.loads(resp.read().decode("utf-8"))
    echo_after = next(
        i for i in (listed_after.get("items") or []) if i.get("dataset_id") == summary["package_id"]
    )
    assert echo_after.get("download_count") == 1
    assert installed["version"] == summary["version"]
    assert installed["digest"].startswith("sha256:")
    assert (home / "plugins" / "index.json").is_file()


def test_reject_dataset_as_plugin(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ageval.registry.archive import build_archive
    from ageval.registry.client import RegistryClient, RegistryError
    from ageval.registry.digest import compute_package_digest

    monkeypatch.setenv("AGEVAL_REGISTRY_URL", registry_server["url"])
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", registry_server["token"])
    _ensure_org(registry_server["url"], registry_server["token"])

    db = REPO / "tests" / "fixtures" / "datasets" / "publish-min"
    archive, blob_digest, size = build_archive(db)
    package_digest = compute_package_digest(db)
    archive_path = tmp_path / "not-plugin.tar.gz"
    archive_path.write_bytes(archive)
    client = RegistryClient(registry_server["url"], token=registry_server["token"])
    with pytest.raises(RegistryError) as ei:
        client.publish(
            dataset_id=f"{TEST_ORG}/not-a-plugin",
            version="0.0.1",
            package_digest=package_digest,
            blob_digest=blob_digest,
            size=size,
            media_type=PLUGIN_MEDIA_TYPE,
            visibility="private",
            archive=archive_path,
            org_id=TEST_ORG,
            package_kind="plugin",
        )
    # Server rejects with non-2xx (client maps to RegistryError).
    assert ei.value.status is None or ei.value.status >= 400
