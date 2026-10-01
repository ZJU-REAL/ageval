"""Shared HTTP loopback check: invoke, workers, and --probe."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ageval.plugins.errors import ExtensionMaterializeError
from ageval.plugins.http_loopback import HTTP_EXECUTORS, is_http_loopback

ROOT = Path(__file__).resolve().parents[2]
JOURNEYS = ROOT / "examples" / "datasets" / "minimal-demo"
_MINISWE_SRC = ROOT / "plugins" / "miniswe" / "src"
if str(_MINISWE_SRC) not in sys.path:
    sys.path.insert(0, str(_MINISWE_SRC))

from miniswe_plugin.factory import MinisweExecutorSPI  # noqa: E402


def _placement() -> SimpleNamespace:
    return SimpleNamespace(user="10001:10001", cwd="/attempt/workspace", env={})


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:4000/v1", True),
        ("http://localhost:8000", True),
        ("http://[::1]:8000/v1", True),
        ("https://127.0.0.1/v1", True),
        ("http://LocalHost/v1", True),
        (None, False),
        ("", False),
        ("https://api.openai.com/v1", False),
        ("http://192.168.1.10:8000/v1", False),
        ("http://10.0.0.8/v1", False),
        ("http://example.com/127.0.0.1", False),
        ("http://evil.test/?x=localhost", False),
        ("http://localhost.example.com/v1", False),
        ("http://127.0.0.1.attacker.test/v1", False),
    ],
)
def test_is_http_loopback_host_only(url: str | None, expected: bool) -> None:
    assert is_http_loopback(url) is expected


def test_http_executors_include_first_party_and_plugin_http_kinds() -> None:
    assert frozenset({"openai-http", "anthropic-http", "dsh", "nooa", "miniswe"}) == HTTP_EXECUTORS


def _load_worker(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dsh_worker_loopback_does_not_emit_missing_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("deepseek_api_key", raising=False)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://127.0.0.1:9/v1")
    worker = ROOT / "plugins" / "dsh" / "worker" / "ageval_executor_dsh.py"
    request = {
        "prompt": "hi",
        "model": "x",
        "workdir": str(tmp_path / "ws"),
        "session_root": str(tmp_path / "sessions"),
        "cordis": str(tmp_path / "missing.cordis.yml"),
    }
    proc = subprocess.run(
        [sys.executable, str(worker), json.dumps(request)],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=os.environ.copy(),
        timeout=30,
    )
    assert proc.stdout.strip(), proc.stderr
    payload = json.loads(proc.stdout)
    assert payload.get("error") != "dsh_missing_credential"


def test_dsh_worker_remote_missing_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("deepseek_api_key", raising=False)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.example.invalid/v1")
    worker = ROOT / "plugins" / "dsh" / "worker" / "ageval_executor_dsh.py"
    proc = subprocess.run(
        [sys.executable, str(worker), json.dumps({"prompt": "hi", "model": "x"})],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=os.environ.copy(),
        timeout=30,
    )
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "dsh_missing_credential"


def test_nooa_worker_loopback_does_not_raise_missing_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("litellm_api_key", raising=False)
    mod = _load_worker(
        ROOT / "plugins" / "nooa" / "worker" / "ageval_executor_nooa.py",
        "ageval_executor_nooa_loopback",
    )
    try:
        mod._build_llm(model="x", api_base="http://127.0.0.1:9/v1", api_key=None)
    except RuntimeError as exc:
        assert "nooa_missing_credential" not in str(exc)
    except ImportError:
        pass


def test_nooa_worker_remote_missing_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("litellm_api_key", raising=False)
    mod = _load_worker(
        ROOT / "plugins" / "nooa" / "worker" / "ageval_executor_nooa.py",
        "ageval_executor_nooa_remote",
    )
    with pytest.raises(RuntimeError, match="nooa_missing_credential"):
        mod._build_llm(model="x", api_base="https://api.example.invalid/v1", api_key=None)


def test_miniswe_loopback_does_not_emit_missing_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("litellm_api_key", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    spi = MinisweExecutorSPI(
        host=SimpleNamespace(kind="local"),
        placement=_placement(),
        model="openai/x",
        api_key=None,
        base_url="http://127.0.0.1:9/v1",
    )
    try:
        spi._run_agent("ping", timeout=1)
    except Exception as exc:
        assert "miniswe_missing_credential" not in str(exc)


def test_miniswe_remote_missing_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("litellm_api_key", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    spi = MinisweExecutorSPI(
        host=SimpleNamespace(kind="local"),
        placement=_placement(),
        model="openai/x",
        api_key=None,
        base_url="https://api.example.invalid/v1",
    )
    with pytest.raises(ExtensionMaterializeError, match="miniswe_missing_credential"):
        spi._run_agent("ping", timeout=1)


def _ageval_probe(
    dataset: Path, profiles: Path, *, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ageval.cli.main",
            "run",
            str(dataset),
            "--task",
            "terminal-jsonl-agg",
            "--profiles",
            str(profiles),
            "--probe",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(dataset),
        env=env,
        timeout=60,
    )


def _http_profiles(path: Path, *, base_url: str, api_key: str | None) -> None:
    lines = [
        "format: ageval.profiles/1",
        "environment: local",
        "agent_profiles:",
        "  solver:",
        "    executor: openai-http",
        "    model: mock",
        f"    base_url: {base_url}",
    ]
    if api_key is not None:
        lines.append(f"    api_key: {api_key}")
    lines.extend(
        [
            "    extensions:",
            "      - plugin: openai-http",
            "      - plugin: local",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def test_probe_loopback_http_without_key_is_not_credential_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    dataset = Path(
        shutil.copytree(
            JOURNEYS, tmp_path / "minimal-demo", ignore=shutil.ignore_patterns(".ageval", ".env")
        )
    )
    profiles = dataset / "profiles.loopback.yaml"
    _http_profiles(profiles, base_url="http://127.0.0.1:9/v1", api_key=None)
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    proc = _ageval_probe(dataset, profiles, env=env)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    data = json.loads(proc.stdout)
    assert data.get("ready") is True
    assert data.get("error") != "credential_missing"
    locked = subprocess.run(
        [
            sys.executable,
            "-m",
            "ageval.cli.main",
            "lock",
            str(dataset),
            "--task",
            "terminal-jsonl-agg",
            "--profiles",
            str(profiles),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(dataset),
        env=env,
        timeout=60,
    )
    assert locked.returncode == 0, locked.stderr
    overlay = json.loads(locked.stdout)["job_overlay"]
    dumped = json.dumps(overlay)
    assert "sk-" not in dumped.lower()
    solver = overlay["agent_profiles"]["solver"]
    assert solver["base_url"] == "http://127.0.0.1:9/v1"
    assert "api_key" not in solver


def test_probe_remote_http_without_key_is_credential_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    dataset = Path(
        shutil.copytree(
            JOURNEYS, tmp_path / "minimal-demo", ignore=shutil.ignore_patterns(".ageval", ".env")
        )
    )
    profiles = dataset / "profiles.remote.yaml"
    _http_profiles(profiles, base_url="https://api.example.invalid/v1", api_key=None)
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    proc = _ageval_probe(dataset, profiles, env=env)
    assert proc.returncode == 2, proc.stdout
    data = json.loads(proc.stdout)
    assert data.get("ready") is False
    assert data.get("error") == "credential_missing"
