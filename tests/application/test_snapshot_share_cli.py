"""CLI snapshot share scrubs secrets and leaves the local suite alone."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from services.registry.app import build_default_state, make_handler
from typer.testing import CliRunner

from ageval.application.composition import build_results_commands
from ageval.cli.main import app
from ageval.registry.client import RegistryClient, RegistryError

SECRET = "sk-supersecretvalue"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_suite(root: Path) -> tuple[Path, Path, Path]:
    suite = root / ".ageval" / "suite-runs" / "suite0001"
    run = root / ".ageval" / "runs" / "run000001"
    suite.mkdir(parents=True)
    run.mkdir(parents=True)
    summary = {
        "suite_run_id": "suite0001",
        "dataset_id": "acme/demo",
        "dataset_version": "0.1.0",
        "status": "finished",
        "exit_code": 0,
        "pass_rate": 1.0,
        "mean_score": 1.0,
        "metrics": {"pass_rate": 1.0, "mean_score": 1.0},
        "task_refs": [{"task_id": "hello", "status": "PASS", "score": 1, "run_id": "run000001"}],
        "job_overlay": {"solver": {"api_key": SECRET, "model": "demo"}},
    }
    summary_path = suite / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (suite / "profiles.yaml").write_text(
        f"solver:\n  api_key: {SECRET}\n  model: demo\n",
        encoding="utf-8",
    )
    result_path = run / "result.json"
    result_path.write_text(
        json.dumps({"status": "PASS", "score": 1, "api_key": SECRET}) + "\n",
        encoding="utf-8",
    )
    (run / "trajectory.jsonl").write_text('{"type":"message","text":"hi"}\n', encoding="utf-8")
    return summary_path, suite / "profiles.yaml", result_path


@pytest.fixture()
def registry_server(tmp_path: Path):
    state, token = build_default_state(
        tmp_path / "reg",
        bootstrap_token="owner-token",
        memory_blob=True,
    )
    handler = make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield {"url": url, "token": token, "state": state}
    server.shutdown()


def test_share_snapshot_prints_url_and_keeps_local_secrets(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "dataset"
    summary_path, profiles_path, result_path = _write_suite(root)
    before = (_sha(summary_path), _sha(profiles_path), _sha(result_path))
    monkeypatch.setenv("AGEVAL_REGISTRY_URL", registry_server["url"])
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", registry_server["token"])
    runner = CliRunner()
    created = runner.invoke(
        app,
        [
            "results",
            "share-snapshot",
            str(root),
            "--suite-run",
            "suite0001",
            "--hub-url",
            "https://hub.example",
            "--registry-url",
            registry_server["url"],
        ],
    )
    assert created.exit_code == 0, created.stdout + created.stderr
    payload = json.loads(created.stdout)
    assert payload["url"] == f"https://hub.example/s/{payload['token']}"
    assert payload["kind"] == "snapshot-share"
    assert before == (_sha(summary_path), _sha(profiles_path), _sha(result_path))
    assert SECRET in summary_path.read_text(encoding="utf-8")
    assert not (root / ".ageval" / "suite-runs" / "suite0001" / "snapshot-share.json").exists()

    anon = RegistryClient(registry_server["url"], token=None)
    view = anon.get_snapshot_share(payload["token"])
    assert SECRET not in json.dumps(view)
    assert view["job_overlay"]["solver"]["api_key"] == "[redacted]"
    file_body = anon._request(
        "GET",
        f"/v1/shares/{payload['token']}/attempts/run000001/files/.ageval/runs/run000001/result.json",
        auth=False,
    )[1].decode()
    assert SECRET not in file_body
    assert "[redacted]" in file_body

    uploaded = build_results_commands().upload_suite_result(
        root,
        suite_run_id="suite0001",
        registry_url=registry_server["url"],
    )
    assert uploaded["visibility"] == "private"
    assert uploaded.get("board_listed") is not True
    state = registry_server["state"]
    with state.stores.results._connect() as conn:
        shares = state.stores.results._exec(
            conn, "SELECT COUNT(*) AS n FROM result_shares"
        ).fetchone()
    assert int(shares["n"]) == 0

    revoked = runner.invoke(
        app,
        [
            "results",
            "revoke-snapshot",
            payload["url"],
            "--registry-url",
            registry_server["url"],
        ],
    )
    assert revoked.exit_code == 0, revoked.stdout + revoked.stderr
    assert json.loads(revoked.stdout)["revoked"] is True
    with pytest.raises(RegistryError) as missing:
        anon.get_snapshot_share(payload["token"])
    assert missing.value.code == "not_found"
    assert before == (_sha(summary_path), _sha(profiles_path), _sha(result_path))


def _invoke(runner: CliRunner, args: list[str]) -> dict:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def test_live_share_reuses_the_token_and_leaves_local_files(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGEVAL_REGISTRY_URL", registry_server["url"])
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", registry_server["token"])
    root = tmp_path / "dataset"
    summary_path, _profiles, result_path = _write_suite(root)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["status"] = "running"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    before = _sha(result_path)
    runner = CliRunner()
    frozen = runner.invoke(
        app,
        [
            "results",
            "share-snapshot",
            str(root),
            "--suite-run",
            "suite0001",
            "--hub-url",
            "https://hub.example",
            "--registry-url",
            registry_server["url"],
        ],
    )
    assert frozen.exit_code == 2
    assert "running" in frozen.stderr

    created = _invoke(
        runner,
        [
            "results",
            "share-snapshot",
            str(root),
            "--suite-run",
            "suite0001",
            "--live",
            "--hub-url",
            "https://hub.example",
            "--registry-url",
            registry_server["url"],
        ],
    )
    assert created["mode"] == "live"
    assert created["url"] == f"https://hub.example/s/{created['token']}"
    sidecar = root / ".ageval" / "suite-runs" / "suite0001" / "live-share.json"
    assert json.loads(sidecar.read_text(encoding="utf-8"))["token"] == created["token"]
    assert SECRET in summary_path.read_text(encoding="utf-8")
    assert _sha(result_path) == before

    state = registry_server["state"]
    with state.stores.results._connect() as conn:
        rows = state.stores.results._exec(
            conn,
            "SELECT path FROM snapshot_share_files WHERE token=?",
            (created["token"],),
        ).fetchall()
    assert rows
    assert all("live-share.json" not in str(row["path"]) for row in rows)
    with state.stores.results._connect() as conn:
        suites = state.stores.results._exec(
            conn, "SELECT COUNT(*) AS n FROM suite_results"
        ).fetchone()
    assert int(suites["n"]) == 0

    summary["status"] = "complete"
    summary["task_refs"][0]["status"] = "FAIL"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    result_path.write_text(
        json.dumps({"status": "FAIL", "score": 0, "api_key": SECRET, "marker": "synced"}) + "\n",
        encoding="utf-8",
    )
    heartbeat = _invoke(
        runner,
        [
            "results",
            "sync-snapshot",
            str(root),
            "--suite-run",
            "suite0001",
            "--heartbeat",
            "--registry-url",
            registry_server["url"],
        ],
    )
    assert heartbeat["token"] == created["token"]
    anon = RegistryClient(registry_server["url"], token=None)
    mid = anon.get_snapshot_share(created["token"])
    assert mid["status"] == "complete"
    held = anon._request(
        "GET",
        f"/v1/shares/{created['token']}/attempts/run000001/files/"
        ".ageval/runs/run000001/result.json",
        auth=False,
    )[1].decode()
    assert "synced" not in held

    synced = _invoke(
        runner,
        [
            "results",
            "sync-snapshot",
            str(root),
            "--suite-run",
            "suite0001",
            "--registry-url",
            registry_server["url"],
        ],
    )
    assert synced["token"] == created["token"]
    again = _invoke(
        runner,
        [
            "results",
            "share-snapshot",
            str(root),
            "--suite-run",
            "suite0001",
            "--live",
            "--hub-url",
            "https://hub.example",
            "--registry-url",
            registry_server["url"],
        ],
    )
    assert again["token"] == created["token"]
    view = anon.get_snapshot_share(created["token"])
    assert view["task_refs"][0]["status"] == "FAIL"
    body = anon._request(
        "GET",
        f"/v1/shares/{created['token']}/attempts/run000001/files/"
        ".ageval/runs/run000001/result.json",
        auth=False,
    )[1].decode()
    assert "synced" in body
    assert SECRET not in body
    assert "[redacted]" in body
    assert SECRET in result_path.read_text(encoding="utf-8")
