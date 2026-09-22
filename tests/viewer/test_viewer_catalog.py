"""Parent-directory viewer: datasets, plugins, agents, confined file preview."""

from __future__ import annotations

import json
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from ageval.plugins.reserved import RESERVED_PLUGIN_IDS
from ageval.registry.cache import PackageCache
from ageval.viewer.server import make_handler, serve_viewer
from ageval.viewer.session import open_view

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"
DIGEST = "sha256:" + ("b" * 64)


def _minimal_spa(tmp_path: Path) -> Path:
    root = tmp_path / "spa"
    root.mkdir()
    (root / "index.html").write_text(
        '<!doctype html><html><body><div id="root"></div></body></html>\n',
        encoding="utf-8",
    )
    return root


def _write_dataset(root: Path, dataset_id: str, *, version: str = "0.1.0") -> None:
    root.mkdir(parents=True)
    (root / "ageval.yaml").write_text(
        "\n".join(
            [
                "format: ageval.dataset/1",
                f"dataset_id: {dataset_id}",
                f'version: "{version}"',
                "tasks:",
                "  root: tasks",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _seed_run(root: Path, run_id: str, dataset_id: str) -> None:
    evidence = root / ".ageval" / "runs" / run_id
    evidence.mkdir(parents=True)
    (evidence / "result.json").write_text(
        json.dumps({"task_id": "alpha", "status": "PASS", "score": 1}) + "\n",
        encoding="utf-8",
    )
    (evidence / "lock.json").write_text(
        json.dumps(
            {
                "task_id": "alpha",
                "dataset_id": dataset_id,
                "dataset_version": "0.1.0",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _parent(root: Path) -> Path:
    _write_dataset(root / "alpha", "test/alpha")
    (root / "alpha" / "README.md").write_text("# Alpha\n", encoding="utf-8")
    (root / "alpha" / "profiles.yaml").write_text("format: ageval.profiles/1\n", encoding="utf-8")
    (root / "alpha" / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (root / "alpha" / "credentials").write_text("do-not-read\n", encoding="utf-8")
    _seed_run(root / "alpha", "run_alpha", "test/alpha")
    _write_dataset(root / "beta", "test/beta")
    (root / "notes.txt").write_text("skip\n", encoding="utf-8")
    (root / "empty-dir").mkdir()
    skipped = root / "not-a-dataset"
    skipped.mkdir()
    (skipped / "ageval.yaml").write_text("format: ageval.plugin/1\n", encoding="utf-8")
    outside = root.parent / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (root / "alpha" / "escape.txt").symlink_to(outside)
    return root


def _install_extras(home: Path) -> None:
    plugin = home / "plugins" / "acme" / "tool" / "0.2.0"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        "format: ageval.plugin/1\nplugin_id: acme/tool\n", encoding="utf-8"
    )
    (plugin / "README.md").write_text("installed plugin\n", encoding="utf-8")
    index = {
        "plugins": [
            {
                "plugin_id": "acme/tool",
                "version": "0.2.0",
                "digest": "sha256:" + ("c" * 64),
                "path": "acme/tool/0.2.0",
                "format": "ageval.plugin/1",
                "slots_summary": {},
            }
        ]
    }
    (home / "plugins" / "index.json").write_text(
        json.dumps(index) + "\n",
        encoding="utf-8",
    )
    agent = home / "agents" / "local" / "extra" / "1.2.3"
    agent.mkdir(parents=True)
    (agent / "agent.yaml").write_text("format: ageval.agent/1\n", encoding="utf-8")
    (agent / "README.md").write_text("installed agent\n", encoding="utf-8")
    agents = {
        "agents": [
            {
                "agent_id": "local/extra",
                "version": "1.2.3",
                "digest": "sha256:" + ("d" * 64),
                "path": "local/extra/1.2.3",
                "format": "ageval.agent/1",
                "label": "Extra",
            }
        ]
    }
    (home / "agents" / "index.json").write_text(json.dumps(agents) + "\n", encoding="utf-8")


def _get(url: str) -> dict:
    with urlopen(url, timeout=5) as resp:  # noqa: S310 — local test server
        return json.loads(resp.read().decode("utf-8"))


def _error(url: str, *, method: str = "GET") -> HTTPError:
    req = Request(url, method=method)  # noqa: S310 — local test server
    try:
        with urlopen(req, timeout=5) as resp:  # noqa: S310
            resp.read()
    except HTTPError as exc:
        return exc
    raise AssertionError(f"expected HTTP error for {url}")


@pytest.fixture()
def parent_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    _install_extras(home)
    parent = _parent(tmp_path / "datasets")
    handler = make_handler(parent, _minimal_spa(tmp_path), session=open_view(parent))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, parent
    server.shutdown()
    server.server_close()


def test_open_view_keeps_one_dataset_root() -> None:
    session = open_view(SUITE)
    assert session.mode == "dataset"
    assert session.landing == "jobs"
    assert [item.key for item in session.datasets] == ["suite-min"]
    assert session.datasets[0].dataset_id == "test/suite-min"


def test_open_view_parent_skips_non_datasets(tmp_path: Path) -> None:
    parent = _parent(tmp_path / "datasets")
    session = open_view(parent)
    assert session.mode == "parent"
    assert session.landing == "datasets"
    assert [item.key for item in session.datasets] == ["alpha", "beta"]
    assert [item.label for item in session.datasets] == ["test/alpha@0.1.0", "test/beta@0.1.0"]


def test_open_view_duplicate_dataset_id_uses_directory_name(tmp_path: Path) -> None:
    root = tmp_path / "siblings"
    _write_dataset(root / "left", "test/same")
    _write_dataset(root / "right", "test/same")
    session = open_view(root)
    assert [item.key for item in session.datasets] == ["left", "right"]
    assert {item.label for item in session.datasets} == {"test/same@0.1.0"}


def test_open_view_registry_ref_is_one_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "cache"
    dest = PackageCache(cache_root).entry_dir("test/suite-min", DIGEST)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SUITE, dest, ignore=shutil.ignore_patterns(".ageval"))
    (dest / ".ageval-verified").write_text(
        json.dumps(
            {
                "schema": "ageval.cache.verified/1",
                "dataset_id": "test/suite-min",
                "package_digest": DIGEST,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGEVAL_CACHE_ROOT", str(cache_root))
    session = open_view("test/suite-min@0.1.0")
    assert session.mode == "dataset"
    assert session.landing == "jobs"
    assert len(session.datasets) == 1
    assert session.datasets[0].root == dest.resolve()


def test_empty_parent_serves_and_lists_builtins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGEVAL_HOME", str(tmp_path / "home"))
    parent = tmp_path / "empty"
    parent.mkdir()
    info = serve_viewer(
        parent,
        host="127.0.0.1",
        port=0,
        open_browser=False,
        block=False,
        dev=True,
    )
    try:
        assert info["dataset_count"] == 0
        assert info["landing"] == "datasets"
        session = _get(f"{info['api_url']}api/session")
        assert session["datasets"] == []
        plugins = _get(f"{info['api_url']}api/plugins")
        builtin = {row["id"] for row in plugins["items"] if row["source"] == "builtin"}
        assert builtin == set(RESERVED_PLUGIN_IDS)
        agents = _get(f"{info['api_url']}api/agents")
        assert any(row["source"] == "builtin" and row["id"] == "pi" for row in agents["items"])
    finally:
        info["server"].shutdown()
        info["server"].server_close()


def test_http_parent_datasets_jobs_and_files(parent_server: tuple[str, Path]) -> None:
    base, parent = parent_server
    session = _get(f"{base}/api/session")
    assert [row["key"] for row in session["datasets"]] == ["alpha", "beta"]
    assert session["landing"] == "datasets"

    missing = _error(f"{base}/api/jobs")
    assert missing.code == 400

    alpha = _get(f"{base}/api/jobs?dataset=alpha")
    assert {item["job_id"] for item in alpha["items"]} == {"run_alpha"}
    beta = _get(f"{base}/api/jobs?dataset=beta")
    assert beta["items"] == []

    other = _error(f"{base}/api/jobs/run_alpha?dataset=beta")
    assert other.code == 404
    assert (parent / "alpha" / ".ageval" / "runs" / "run_alpha").is_dir()

    package = _get(f"{base}/api/datasets/alpha")
    assert package["readme"] == "README.md"
    assert package["manifest"] == "ageval.yaml"
    assert package["profiles"] == "profiles.yaml"
    readme = _get(f"{base}/api/datasets/alpha/file?{urlencode({'path': 'README.md'})}")
    assert readme["content"] == "# Alpha\n"
    tree = _get(f"{base}/api/datasets/alpha/tree")
    paths = {entry["path"] for entry in tree["entries"]}
    assert "ageval.yaml" in paths
    assert "profiles.yaml" in paths
    assert "README.md" in paths
    assert not any(path == ".ageval/runs" or path.startswith(".ageval/runs/") for path in paths)
    assert not any(
        path == ".ageval/suite-runs" or path.startswith(".ageval/suite-runs/") for path in paths
    )

    redacted = _get(f"{base}/api/datasets/alpha/file?{urlencode({'path': '.env'})}")
    assert redacted["encoding"] == "redacted"
    assert redacted["content"] is None

    for rel in ("credentials", "../outside.txt", "/etc/passwd", "escape.txt"):
        refused = _error(f"{base}/api/datasets/alpha/file?{urlencode({'path': rel})}")
        assert refused.code == 400, rel


def test_http_delete_stays_on_selected_dataset(parent_server: tuple[str, Path]) -> None:
    base, parent = parent_server
    wrong = _error(f"{base}/api/jobs/run_alpha/delete-preview?dataset=beta")
    assert wrong.code == 404
    assert (parent / "alpha" / ".ageval" / "runs" / "run_alpha" / "result.json").is_file()
    preview = _get(f"{base}/api/jobs/run_alpha/delete-preview?dataset=alpha")
    query = urlencode({"dataset": "alpha", "confirm": preview["confirm_token"]})
    deleted = _get_delete(f"{base}/api/jobs/run_alpha?{query}")
    assert deleted["ok"] is True
    assert not (parent / "alpha" / ".ageval" / "runs" / "run_alpha").exists()
    assert (parent / "beta").is_dir()


def _get_delete(url: str) -> dict:
    req = Request(url, method="DELETE")  # noqa: S310 — local test server
    with urlopen(req, timeout=5) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def test_http_builtin_and_installed_packages(parent_server: tuple[str, Path]) -> None:
    base, _parent = parent_server
    plugins = _get(f"{base}/api/plugins")
    builtin = {row["id"] for row in plugins["items"] if row["source"] == "builtin"}
    assert builtin == set(RESERVED_PLUGIN_IDS)
    installed = [row for row in plugins["items"] if row["source"] == "installed"]
    assert installed == [
        {
            "source": "installed",
            "id": "acme/tool",
            "version": "0.2.0",
            "label": "acme/tool",
            "description": None,
            "read_only": True,
        }
    ]
    local = next(
        row for row in plugins["items"] if row["id"] == "local" and row["source"] == "builtin"
    )
    query = urlencode({"source": "builtin", "id": "local", "version": local["version"]})
    package = _get(f"{base}/api/plugins/package?{query}")
    assert package["manifest"] == "plugin.yaml"
    tree = _get(f"{base}/api/plugins/tree?{query}")
    assert any(entry["path"] == "plugin.yaml" for entry in tree["entries"])
    readme = _get(f"{base}/api/plugins/file?{query}&{urlencode({'path': 'README.md'})}")
    assert readme["encoding"] == "utf-8"
    assert readme["content"]

    agents = _get(f"{base}/api/agents")
    assert any(row["id"] == "local/extra" and row["version"] == "1.2.3" for row in agents["items"])
    pi = next(row for row in agents["items"] if row["source"] == "builtin" and row["id"] == "pi")
    agent_q = urlencode({"source": "builtin", "id": "pi", "version": pi["version"]})
    agent = _get(f"{base}/api/agents/package?{agent_q}")
    assert agent["manifest"] == "agent.yaml"
    agent_tree = _get(f"{base}/api/agents/tree?{agent_q}")
    assert any(entry["path"] == "agent.yaml" for entry in agent_tree["entries"])

    home_file = _error(
        f"{base}/api/plugins/file?{query}&{urlencode({'path': '../../credentials'})}"
    )
    assert home_file.code == 400
