"""Viewer Share / Unshare talks to a real registry and leaves local files in place."""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from services.registry.app import build_default_state, make_handler

from ageval.viewer.server import make_handler as make_viewer

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _request(url: str, *, method: str = "GET", body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, method=method, headers=headers)
    with urlopen(req, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


@pytest.fixture()
def servers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state, token = build_default_state(
        tmp_path / "reg", bootstrap_token="owner-token", memory_blob=True
    )
    registry = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=registry.serve_forever, daemon=True).start()
    registry_url = f"http://127.0.0.1:{registry.server_address[1]}"
    monkeypatch.setenv("AGEVAL_REGISTRY_URL", registry_url)
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", token)
    monkeypatch.setenv("AGEVAL_HUB_URL", "https://hub.example")

    db = tmp_path / "dataset"
    shutil.copytree(SUITE, db, ignore=shutil.ignore_patterns(".ageval"))
    summary = db / ".ageval" / "suite-runs" / "suite0001" / "summary.json"
    result = db / ".ageval" / "runs" / "run000001" / "result.json"
    _write(
        summary,
        {
            "suite_run_id": "suite0001",
            "dataset_id": "acme/demo",
            "dataset_version": "0.1.0",
            "status": "finished",
            "task_refs": [
                {"task_id": "hello", "status": "PASS", "score": 1, "run_id": "run000001"}
            ],
            "job_overlay": {"solver": {"api_key": "sk-supersecretvalue"}},
        },
    )
    _write(
        result, {"task_id": "hello", "status": "PASS", "score": 1, "api_key": "sk-supersecretvalue"}
    )
    single_lock = db / ".ageval" / "runs" / "solo0001" / "lock.json"
    single_result = db / ".ageval" / "runs" / "solo0001" / "result.json"
    _write(single_lock, {"dataset_id": "acme/demo", "dataset_version": "0.1.0", "task_id": "solo"})
    _write(single_result, {"task_id": "solo", "status": "PASS", "score": 1})

    spa = tmp_path / "spa"
    spa.mkdir()
    (spa / "index.html").write_text(
        "<!doctype html><title>ageval Viewer</title>\n", encoding="utf-8"
    )
    viewer = ThreadingHTTPServer(("127.0.0.1", 0), make_viewer(db, spa))
    threading.Thread(target=viewer.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{viewer.server_address[1]}"
    try:
        yield {
            "base": base,
            "root": db,
            "summary": summary,
            "result": result,
            "before": (_sha(summary), _sha(result)),
        }
    finally:
        viewer.shutdown()
        viewer.server_close()
        registry.shutdown()
        registry.server_close()


def test_viewer_share_and_unshare_suite_and_job(servers: dict) -> None:
    base = servers["base"]
    idle = _request(f"{base}/api/jobs/suite0001/share")
    assert idle["shared"] is False

    created = _request(f"{base}/api/jobs/suite0001/share", method="POST")
    assert created["shared"] is True
    assert created["url"] == f"https://hub.example/s/{created['token']}"
    assert created["run_id"] == ""
    assert servers["before"] == (_sha(servers["summary"]), _sha(servers["result"]))
    assert "sk-supersecretvalue" in servers["summary"].read_text(encoding="utf-8")

    again = _request(f"{base}/api/jobs/suite0001/share")
    assert again["token"] == created["token"]

    job = _request(f"{base}/api/jobs/suite0001/share?run_id=run000001", method="POST")
    assert job["run_id"] == "run000001"
    assert job["token"] != created["token"]
    assert _request(f"{base}/api/jobs/suite0001/share")["token"] == created["token"]

    single = _request(f"{base}/api/jobs/solo0001/share?run_id=solo0001", method="POST")
    assert single["shared"] is True
    assert single["suite_run_id"] == "solo0001"

    revoked = _request(f"{base}/api/jobs/suite0001/share", method="DELETE")
    assert revoked["revoked"] is True
    assert _request(f"{base}/api/jobs/suite0001/share")["shared"] is False
    assert _request(f"{base}/api/jobs/suite0001/share?run_id=run000001")["shared"] is True
    assert servers["before"] == (_sha(servers["summary"]), _sha(servers["result"]))


def test_viewer_suite_share_can_be_live(servers: dict) -> None:
    base = servers["base"]
    created = _request(f"{base}/api/jobs/suite0001/share", method="POST", body={"live": True})
    assert created["mode"] == "live"
    assert created["shared"] is True
    side = servers["root"] / ".ageval" / "suite-runs" / "suite0001" / "live-share.json"
    saved = json.loads(side.read_text(encoding="utf-8"))
    assert saved["token"] == created["token"]
    status = _request(f"{base}/api/jobs/suite0001/share")
    assert status["mode"] == "live"
    assert status["token"] == created["token"]

    req = Request(
        f"{base}/api/jobs/suite0001/share?run_id=run000001",
        data=json.dumps({"live": True}).encode("utf-8"),
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as denied:
        urlopen(req, timeout=10)  # noqa: S310
    assert denied.value.code == 400

    revoked = _request(f"{base}/api/jobs/suite0001/share", method="DELETE")
    assert revoked["revoked"] is True
    assert side.is_file() is False
    assert _request(f"{base}/api/jobs/suite0001/share")["shared"] is False
