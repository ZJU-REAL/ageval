"""ACP static registry loader and readiness."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from tests.helpers.lock import CONFIG_MIN, job_document, lock_task

from ageval.config.capabilities import DeclarationCapabilityCatalog
from ageval.config.errors import ConfigError
from ageval.config.profiles import JobDocument
from ageval.environments.protocol import EnvironmentFailure
from ageval.plugins.contrib.acp.home import _copy_keyless_auth
from ageval.plugins.contrib.acp.registry import (
    AcpRegistryError,
    clear_registry_cache,
    get_entry,
    list_entry_ids,
    load_acp_entries,
    peek_acp_entries,
    readiness_for,
)

_PACKAGED_DIGESTS = {
    "claude-code": "sha256:5ccb5fd4ab06f58d15a6bd1c9cc903545edf45716d30fa4298d113cb82f69085",
    "codex": "sha256:b783adb06eef41e6afa8bbd012069581e5cac87c3f99d22e7ac87a3695e71cbe",
    "grok-build": "sha256:427d622f1fd36141e81fbdd9b9cdfe15fe14478884247285d7fb5dfc3d57a57f",
    "opencode": "sha256:2d1bc6f0d4c39824f43412b06c4957070b36f832ace1b894d8e3775e0c22835a",
    "pi": "sha256:9148f4c07b4b4f82fe552928558b0980e2ec50cd0cade3d9c9c10aa572e50026",
}
_PACKAGED = Path(__file__).resolve().parents[2] / "src/ageval/plugins/contrib/acp/acp_entries.json"
_EVAL_JUDGE = Path(__file__).resolve().parents[1] / "fixtures/datasets/eval-judge-min"


def _home_file(doc: dict[str, object]) -> None:
    path = Path(os.environ["AGEVAL_HOME"]) / "acp-entries.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    clear_registry_cache()


def _kimi_doc(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "entry_id": "kimi",
        "integration_mode": 2,
        "execution_mode": "acp-stdio",
        "engine_detect_commands": ["kimi"],
        "acp_command": ["kimi", "acp"],
        "acp_detect_commands": ["kimi"],
        "acp_package": "@moonshot-ai/kimi-code",
        "acp_version": "1.2.3",
        "install_command": "npm install -g @moonshot-ai/kimi-code@1.2.3",
        "credential_env_names": ["KIMI_API_KEY"],
        "model_binding": "config-option",
        "platforms": ["darwin", "linux"],
    }
    row.update(overrides)
    return {"schema_version": 1, "entries": [row]}


def _acp_job(entry: str) -> JobDocument:
    return job_document(
        {
            "solver": {
                "executor": "acp",
                "model": {"id": "entry-default"},
                "options": {"entry": entry},
                "extensions": [{"plugin": "acp"}, {"plugin": "local"}],
            }
        }
    )


def test_registry_loads_five_entries() -> None:
    clear_registry_cache()
    entries = load_acp_entries()
    assert set(entries) == {"codex", "claude-code", "pi", "opencode", "grok-build"}
    for eid in list_entry_ids():
        desc = entries[eid]
        assert desc.execution_mode == "acp-stdio"
        assert desc.descriptor_digest.startswith("sha256:")
        assert desc.acp_command
        assert "latest" not in " ".join(desc.acp_command)
    # Every official entry can authenticate from a file it declares, and every
    # declared path stays under HOME.
    for desc in entries.values():
        assert desc.keyless_auth is True
        assert desc.keyless_auth_paths
        for rel in (*desc.home_dirs, *desc.keyless_auth_paths):
            assert not rel.startswith("/")
            assert ".." not in rel


def test_unknown_entry() -> None:
    assert get_entry("not-a-real-entry") is None


def test_duplicate_entry_rejected(tmp_path: Path) -> None:
    clear_registry_cache()
    src = Path(__file__).resolve().parents[2] / "src/ageval/plugins/contrib/acp/acp_entries.json"
    doc = json.loads(src.read_text(encoding="utf-8"))
    doc["entries"].append(doc["entries"][0])
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(AcpRegistryError, match="duplicate") as raised:
        load_acp_entries(str(bad))
    assert raised.value.error_code == "acp_entry_duplicate"
    clear_registry_cache()


def test_adapter_missing_readiness() -> None:
    desc = get_entry("codex")
    assert desc is not None

    def which(name: str) -> str | None:
        if name == "codex":
            return "/fake/codex"
        return None

    row = readiness_for(desc, which=which)
    assert row["engine_ready"] is True
    assert row["acp_entry_ready"] is False
    assert row["readiness"] == "adapter-missing"


def test_mode2_entry_missing() -> None:
    desc = get_entry("opencode")
    assert desc is not None

    def which(_name: str) -> str | None:
        return None

    row = readiness_for(desc, which=which)
    assert row["readiness"] == "entry-missing"


def test_lock_snapshot_has_no_paths_or_secrets() -> None:
    desc = get_entry("pi")
    assert desc is not None
    snap = desc.as_lock_snapshot()
    blob = json.dumps(snap)
    assert "secret" not in blob.lower() or "credential_env" in blob
    assert "/Users" not in blob
    assert "/home" not in blob
    assert "sk-" not in blob
    assert snap["entry_id"] == "pi"
    assert snap["acp_version"] == "0.0.33"
    assert "source" not in snap


def test_packaged_digests_ignore_source() -> None:
    entries = load_acp_entries()
    assert {eid: desc.descriptor_digest for eid, desc in entries.items()} == _PACKAGED_DIGESTS
    assert {desc.source for desc in entries.values()} == {"package"}


def test_absent_home_file_is_the_packaged_table() -> None:
    assert list_entry_ids() == ["claude-code", "codex", "grok-build", "opencode", "pi"]


def test_home_file_adds_a_user_entry_and_lock_accepts_it() -> None:
    _home_file(_kimi_doc())
    desc = get_entry("kimi")
    assert desc is not None
    assert desc.source == "user"
    assert "source" not in desc.as_lock_snapshot()
    locked = lock_task(CONFIG_MIN, "minimal", job=_acp_job("kimi"))
    assert locked.task_id == "minimal"
    pi = lock_task(CONFIG_MIN, "minimal", job=_acp_job("pi"))
    assert pi.task_id == "minimal"


def test_explicit_path_does_not_merge_the_home_file() -> None:
    _home_file(_kimi_doc())
    entries = load_acp_entries(str(_PACKAGED))
    assert "kimi" not in entries
    assert entries["pi"].source == "package"


def test_home_entry_cannot_replace_a_packaged_id() -> None:
    _home_file(_kimi_doc(entry_id="pi"))
    with pytest.raises(AcpRegistryError) as raised:
        load_acp_entries()
    assert raised.value.error_code == "acp_entry_id_collision"
    assert raised.value.location == "/entries/0/entry_id"
    assert peek_acp_entries() is None


def test_supports_acp_entry_reads_the_cache_and_does_not_raise() -> None:
    clear_registry_cache()
    catalog = DeclarationCapabilityCatalog()
    assert peek_acp_entries() is None
    assert catalog.supports_acp_entry("pi") is False
    _home_file({"schema_version": 2, "entries": []})
    with pytest.raises(AcpRegistryError):
        load_acp_entries()
    assert catalog.supports_acp_entry("pi") is False
    _home_file(_kimi_doc())
    load_acp_entries()
    assert catalog.supports_acp_entry("kimi") is True
    assert catalog.supports_acp_entry("missing") is False


def test_home_file_failures_use_one_code(tmp_path: Path) -> None:
    cases: list[tuple[object, str]] = [
        ("{", "acp_user_entries_unreadable"),
        ({"schema_version": 2, "entries": []}, "invalid_schema"),
        ({"entries": []}, "invalid_schema"),
        ({"schema_version": 1, "protocol_version": 1, "entries": []}, "invalid_schema"),
        (_kimi_doc(acp_command=["npx", "kimi"]), "acp_install_npx"),
        (
            _kimi_doc(
                acp_version="1.2.x", install_command="npm install -g @moonshot-ai/kimi-code@1.2.x"
            ),
            "acp_install_unpinned",
        ),
        (_kimi_doc(fixed_env={"HOME": "1"}), "invalid_schema"),
        (
            _kimi_doc(
                home_dirs=[".config"],
                keyless_auth_paths=[".config/auth.json"],
            ),
            "invalid_schema",
        ),
    ]
    for doc, code in cases:
        path = Path(os.environ["AGEVAL_HOME"]) / "acp-entries.json"
        path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
        clear_registry_cache()
        with pytest.raises(AcpRegistryError) as raised:
            load_acp_entries()
        assert raised.value.error_code == code
    huge = Path(os.environ["AGEVAL_HOME"]) / "acp-entries.json"
    huge.write_bytes(b"{" + b" " * (64 * 1024))
    clear_registry_cache()
    with pytest.raises(AcpRegistryError) as raised:
        load_acp_entries()
    assert raised.value.error_code == "acp_user_entries_unreadable"
    assert raised.value.location == "acp-entries.json"
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_kimi_doc()), encoding="utf-8")
    link = Path(os.environ["AGEVAL_HOME"]) / "acp-entries.json"
    link.unlink()
    link.symlink_to(outside)
    clear_registry_cache()
    with pytest.raises(AcpRegistryError) as raised:
        load_acp_entries()
    assert raised.value.error_code == "acp_user_entries_unreadable"


def test_bad_home_file_stops_pi_and_non_acp_locks() -> None:
    _home_file({"schema_version": 2, "entries": []})
    with pytest.raises(ConfigError) as pi_lock:
        lock_task(CONFIG_MIN, "minimal", job=_acp_job("pi"))
    assert pi_lock.value.error_code == "invalid_schema"
    assert "1" in pi_lock.value.message
    with pytest.raises(ConfigError) as http_lock:
        lock_task(_EVAL_JUDGE, "judge-score")
    assert http_lock.value.error_code == "invalid_schema"


def test_symlink_auth_path_stops_before_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "real.json"
    target.write_text("{}", encoding="utf-8")
    auth_dir = tmp_path / ".codex"
    auth_dir.mkdir()
    (auth_dir / "auth.json").symlink_to(target)
    monkeypatch.setattr(
        "ageval.plugins.contrib.acp.home.Path.home",
        lambda: tmp_path,
    )
    desc = get_entry("codex")
    assert desc is not None

    async def _run() -> None:
        await _copy_keyless_auth(None, desc)

    with pytest.raises(EnvironmentFailure) as raised:
        asyncio.run(_run())
    assert raised.value.kind == "acp_auth_path_symlink"
