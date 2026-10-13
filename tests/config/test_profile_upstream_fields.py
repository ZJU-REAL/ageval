"""Profile base_url + api_key (env locator) config validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from tests.helpers.lock import lock_with_profiles

from ageval.config.errors import ConfigError
from ageval.config.model import thaw

REPO = Path(__file__).resolve().parents[2]


def _write_pkg(tmp: Path, *, slot_id: str = "glm") -> Path:
    pkg = tmp / "pkg"
    pkg.mkdir()
    (pkg / "run.py").write_text("async def run(ctx):\n    pass\n", encoding="utf-8")
    (pkg / "evaluator.py").write_text("def evaluate(i):\n    return {}\n", encoding="utf-8")
    doc = {
        "format": "ageval.task/1",
        "task_id": "profile-upstream",
        "parameters": {},
        "agent_profiles": [{"id": slot_id}],
        "limits": {
            "wall_time_seconds": 60,
            "agent_invocations": 1,
        },
        "artifacts": {"publishable": []},
        "evaluation": {
            "entrypoint": "evaluator:evaluate",
            "inputs": [],
        },
    }
    (pkg / "task.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    return pkg


def test_accepts_base_url_and_api_key_locator(tmp_path: Path) -> None:
    pkg = _write_pkg(tmp_path, slot_id="glm")
    locked = lock_with_profiles(
        pkg,
        "profile-upstream",
        {
            "glm": {
                "executor": "openai-http",
                "model": {"id": "glm-4.7"},
                "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
                "api_key": "${zhipu_coding_api_key}",
            }
        },
    )
    profiles = thaw(locked.agent_profiles)
    assert profiles[0]["base_url"].startswith("https://")
    assert profiles[0]["api_key"] == "zhipu_coding_api_key"


def test_rejects_secret_like_api_key(tmp_path: Path) -> None:
    pkg = _write_pkg(tmp_path, slot_id="bad")
    with pytest.raises(ConfigError) as ei:
        lock_with_profiles(
            pkg,
            "profile-upstream",
            {
                "bad": {
                    "executor": "openai-http",
                    "model": {"id": "glm-4.7"},
                    "api_key": "sk-this-is-a-secret-value-not-a-locator",
                }
            },
        )
    assert "api_key" in str(ei.value).lower() or ei.value.error_code == "invalid_schema"


def test_rejects_non_url_base(tmp_path: Path) -> None:
    pkg = _write_pkg(tmp_path, slot_id="bad")
    with pytest.raises(ConfigError):
        lock_with_profiles(
            pkg,
            "profile-upstream",
            {
                "bad": {
                    "executor": "openai-http",
                    "model": {"id": "glm-4.7"},
                    "base_url": "not-a-url",
                }
            },
        )


def test_unwraps_base_url_env_ref_to_locator_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_LITELLM_BASE", "http://127.0.0.1:8010/v1")
    pkg = _write_pkg(tmp_path, slot_id="glm")
    locked = lock_with_profiles(
        pkg,
        "profile-upstream",
        {
            "glm": {
                "executor": "openai-http",
                "model": {"id": "glm-4.7"},
                "base_url": "${TEST_LITELLM_BASE}",
                "api_key": "${zhipu_coding_api_key}",
            }
        },
    )
    profiles = thaw(locked.agent_profiles)
    assert profiles[0]["base_url"] == "TEST_LITELLM_BASE"
    assert profiles[0]["api_key"] == "zhipu_coding_api_key"
    overlay = thaw(locked.job_overlay)
    assert overlay["agent_profiles"]["glm"]["base_url"] == "TEST_LITELLM_BASE"
    payload = str(thaw(locked.job_overlay)) + str(profiles)
    assert "127.0.0.1" not in payload


def test_rejects_bare_base_url_locator(tmp_path: Path) -> None:
    pkg = _write_pkg(tmp_path, slot_id="glm")
    with pytest.raises(ConfigError, match=r"\$\{ENV_NAME\}|http\(s\)"):
        lock_with_profiles(
            pkg,
            "profile-upstream",
            {
                "glm": {
                    "executor": "openai-http",
                    "model": {"id": "glm-4.7"},
                    "base_url": "litellm_base_url",
                    "api_key": "${zhipu_coding_api_key}",
                }
            },
        )


def test_rejects_bare_api_key_locator(tmp_path: Path) -> None:
    pkg = _write_pkg(tmp_path, slot_id="glm")
    with pytest.raises(ConfigError, match=r"\$\{ENV_NAME\}"):
        lock_with_profiles(
            pkg,
            "profile-upstream",
            {
                "glm": {
                    "executor": "openai-http",
                    "model": {"id": "glm-4.7"},
                    "api_key": "zhipu_coding_api_key",
                }
            },
        )


def test_lock_keeps_unset_base_url_locator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_BASE_URL", raising=False)
    pkg = _write_pkg(tmp_path, slot_id="glm")
    locked = lock_with_profiles(
        pkg,
        "profile-upstream",
        {
            "glm": {
                "executor": "openai-http",
                "model": {"id": "glm-4.7"},
                "base_url": "${MISSING_BASE_URL}",
                "api_key": "${zhipu_coding_api_key}",
            }
        },
    )
    assert thaw(locked.agent_profiles)[0]["base_url"] == "MISSING_BASE_URL"


def test_resolve_locked_base_url_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from ageval.config.env_refs import resolve_locked_base_url

    monkeypatch.setenv("TEST_LITELLM_BASE", "http://127.0.0.1:8010/v1")
    assert resolve_locked_base_url("TEST_LITELLM_BASE") == "http://127.0.0.1:8010/v1"
    assert resolve_locked_base_url("https://example.test/v1") == "https://example.test/v1"
    monkeypatch.delenv("MISSING_BASE_URL", raising=False)
    with pytest.raises(ConfigError, match="unset"):
        resolve_locked_base_url("MISSING_BASE_URL")
