"""design/14: publish agent → preview → list filter → install; secrets rejected."""

from __future__ import annotations

import contextlib
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from services.registry.app import build_default_state, make_handler

from ageval.application.composition import build_agent_commands
from ageval.registry.client import RegistryClient
from ageval.registry.media_types import AGENT_MEDIA_TYPE

_agents = build_agent_commands()
install_agent_from_registry = _agents.install_agent_from_registry
publish_agent = _agents.publish_agent

REPO = Path(__file__).resolve().parents[2]
AGENT_FIXTURE = REPO / "tests" / "fixtures" / "agents" / "pi-default"
TEST_ORG = "test"


@pytest.fixture()
def registry_server(tmp_path: Path):
    data = tmp_path / "reg-data"
    state, token = build_default_state(data, bootstrap_token="test-token-agent", memory_blob=True)
    handler = make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    yield {"url": url, "token": token, "state": state}
    server.shutdown()


@pytest.fixture()
def env(registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("AGEVAL_REGISTRY_URL", registry_server["url"])
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", registry_server["token"])
    home = tmp_path / "ageval-home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    client = RegistryClient(registry_server["url"], token=registry_server["token"])
    with contextlib.suppress(Exception):  # already created
        client.create_org(name=TEST_ORG, display_name="Test Org")
    return {"url": registry_server["url"], "token": registry_server["token"], "home": str(home)}


def _get(url: str, token: str, path: str) -> dict:
    req = urllib.request.Request(url + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def test_publish_agent_preview_list_and_install(env: dict[str, str]) -> None:
    summary = publish_agent(AGENT_FIXTURE, public=False, org=TEST_ORG)
    assert summary["ok"] is True
    assert summary["package_kind"] == "agent"
    assert summary["media_type"] == AGENT_MEDIA_TYPE
    assert summary["package_id"] == f"{TEST_ORG}/pi-default"

    body = _get(
        env["url"],
        env["token"],
        f"/v1/packages/{summary['package_id']}/versions/{summary['version']}",
    )
    assert body.get("package_kind") == "agent"
    preview = body.get("agent_preview") or {}
    assert preview.get("agent_id") == "pi-default"
    assert preview.get("label") == "Pi (entry default)"
    assert preview.get("binding", {}).get("executor") == "acp"
    assert "agent.yaml" in (preview.get("files") or [])

    listed = _get(env["url"], env["token"], "/v1/packages?package_kind=agent")
    items = listed.get("items") or []
    assert any(i.get("dataset_id") == summary["package_id"] for i in items)
    assert all(i.get("package_kind") == "agent" for i in items)

    db_listed = _get(env["url"], env["token"], "/v1/packages?package_kind=dataset")
    assert not any(
        i.get("dataset_id") == summary["package_id"] for i in (db_listed.get("items") or [])
    )

    installed = install_agent_from_registry(summary["ref"])
    assert installed["ok"] is True
    assert installed["agent_id"] == f"{TEST_ORG}/pi-default"
    assert installed["digest"].startswith("sha256:")
    assert (Path(env["home"]) / "agents" / "index.json").is_file()

    # Install by digest round-trips too.
    by_digest = install_agent_from_registry(f"{summary['package_id']}@{summary['package_digest']}")
    assert by_digest["ok"] is True


def test_publish_agent_archives_listed_overlays(env: dict[str, str], tmp_path: Path) -> None:
    pkg = tmp_path / "overlay-agent"
    pkg.mkdir()
    (pkg / "agent.yaml").write_text(
        "format: ageval.agent/1\nagent_id: overlay-demo\nversion: '1.0'\n"
        "binding:\n  executor: openai-http\n  model: none\n"
        "  overlays: [overlays/skills/demo]\n",
        encoding="utf-8",
    )
    skill = pkg / "overlays" / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# demo\n", encoding="utf-8")

    summary = publish_agent(pkg, public=False, org=TEST_ORG)
    assert summary["ok"] is True
    body = _get(
        env["url"],
        env["token"],
        f"/v1/packages/{summary['package_id']}/versions/{summary['version']}",
    )
    files = body.get("agent_preview", {}).get("files") or []
    assert "overlays/skills/demo/SKILL.md" in files

    installed = install_agent_from_registry(summary["ref"])
    assert installed["ok"] is True
    cached = (
        Path(env["home"])
        / "agents"
        / installed["agent_id"]
        / installed["version"]
        / "overlays"
        / "skills"
        / "demo"
        / "SKILL.md"
    )
    assert cached.is_file()
    assert not (pkg.parent / "dataset-overlays").exists()


def test_publish_rejects_missing_listed_overlay(env: dict[str, str], tmp_path: Path) -> None:
    from ageval.config.errors import ConfigError

    pkg = tmp_path / "missing-overlay-agent"
    pkg.mkdir()
    (pkg / "agent.yaml").write_text(
        "format: ageval.agent/1\nagent_id: missing-ov\nversion: '1.0'\n"
        "binding:\n  executor: openai-http\n  model: none\n"
        "  overlays: [overlays/skills/demo]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as ei:
        publish_agent(pkg, public=False, org=TEST_ORG)
    assert ei.value.error_code == "missing_reference"


def test_reject_secret_bearing_agent(env: dict[str, str], tmp_path: Path) -> None:
    from ageval.config.errors import ConfigError

    pkg = tmp_path / "leaky-agent"
    pkg.mkdir()
    (pkg / "agent.yaml").write_text(
        "format: ageval.agent/1\nagent_id: leaky\nversion: '1.0'\n"
        "binding: {executor: openai-http, model: none}\n",
        encoding="utf-8",
    )
    (pkg / "notes.txt").write_text("api_key = sk-abc123def456ghi789jkl000\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        publish_agent(pkg, public=False, org=TEST_ORG)


def test_reject_agent_yaml_as_dataset(env: dict[str, str], tmp_path: Path) -> None:
    """agent.yaml trees must not slip through as package_kind=dataset.

    The client already fails closed locally (no ageval.yaml); the server guard
    in ``_validate_archive`` is exercised directly as defense in depth.
    """
    import tarfile

    from services.registry.http_api import RegistryAppError
    from services.registry.package_service import PackageService

    pkg = tmp_path / "sneaky"
    pkg.mkdir()
    (pkg / "agent.yaml").write_text(
        "format: ageval.agent/1\nagent_id: sneaky\nversion: '1.0'\n"
        "binding: {executor: openai-http, model: none}\n",
        encoding="utf-8",
    )
    # Hand-rolled tarball: ageval.registry.archive validates dataset trees.
    archive_path = tmp_path / "sneaky.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(pkg / "agent.yaml", arcname="agent.yaml")

    svc = PackageService.__new__(PackageService)  # _validate_archive uses no self state
    with pytest.raises(RegistryAppError) as exc:
        svc._validate_archive(
            archive_path,
            package_kind="dataset",
            media_type="application/vnd.ageval.dataset.v1.tar+gzip",
            package_digest="sha256:" + "0" * 64,  # guard fires before digest compare
        )
    assert "package_kind=agent" in str(exc.value)
