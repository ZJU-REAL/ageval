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
from ageval.config.load_and_lock import referenced_acp_user_entries
from ageval.config.model import locked_to_summary, thaw
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
    "claude-code": "sha256:8565d14d5e0b69397a7f818b9b151be73d17c22bfda19a51cdf55ab668c4b784",
    "codex": "sha256:36e5ad2d6071b68806cbecd57a4a0993e497bb308813a28ff4954cafd65f86a9",
    "grok-build": "sha256:bb01b57b43c8e9866bdc56c6656fee4da5e787004020f4becf51dcdc9a6fe7dd",
    "opencode": "sha256:515cc3a7a21dcc9d0e426d20b669025ba0e6af265a4e6714be01219edef47c98",
    "pi": "sha256:69f120be48644f1efde0266b64e189a45fe41e3283833eba9774f282bccef148",
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
        "runtime": {"node": ">=18.0.0"},
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


# Max published engines.node at the current pin. A pin with no engines.node
# does not raise the floor. opencode publishes none, so the floor is >=18.0.0.
_NODE_FLOORS = {
    "claude-code": ">=22.0.0",
    "codex": ">=16.0.0",
    "grok-build": ">=20.0.0",
    "opencode": ">=18.0.0",
    "pi": ">=22.19.0",
}


def test_packaged_entries_store_resolved_node_floors() -> None:
    entries = load_acp_entries()
    assert {eid: desc.runtime.node_spec() for eid, desc in entries.items()} == _NODE_FLOORS
    pi = entries["pi"]
    assert pi.runtime.node == (22, 19, 0)
    assert pi.as_dict()["runtime"] == {"node": ">=22.19.0"}


def test_runtime_node_canonicalizes_and_rejects_other_shapes(tmp_path: Path) -> None:
    short = _kimi_doc(runtime={"node": ">=22"})
    path = tmp_path / "short.json"
    path.write_text(json.dumps(short), encoding="utf-8")
    clear_registry_cache()
    desc = load_acp_entries(str(path))["kimi"]
    assert desc.runtime.node_spec() == ">=22.0.0"
    full = _kimi_doc(runtime={"node": ">=22.0.0"})
    full_path = tmp_path / "full.json"
    full_path.write_text(json.dumps(full), encoding="utf-8")
    clear_registry_cache()
    assert load_acp_entries(str(full_path))["kimi"].descriptor_digest == desc.descriptor_digest

    missing = _kimi_doc()
    rows = missing["entries"]
    assert isinstance(rows, list)
    row = rows[0]
    assert isinstance(row, dict)
    row.pop("runtime")
    bad_docs: list[tuple[dict[str, object], str]] = [
        (missing, "/entries/0/runtime"),
        (_kimi_doc(runtime={"python": ">=3.12"}), "/entries/0/runtime/python"),
        (_kimi_doc(runtime={"node": "^22"}), "/entries/0/runtime/node"),
        (_kimi_doc(runtime=[]), "/entries/0/runtime"),
    ]
    for index, (doc, location) in enumerate(bad_docs):
        target = tmp_path / f"bad-{index}.json"
        target.write_text(json.dumps(doc), encoding="utf-8")
        clear_registry_cache()
        with pytest.raises(AcpRegistryError) as raised:
            load_acp_entries(str(target))
        assert raised.value.error_code == "invalid_schema"
        assert raised.value.location == location


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
    assert snap["runtime"] == {"node": ">=22.19.0"}
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


def test_packaged_lock_omits_acp_user_entries() -> None:
    locked = lock_task(CONFIG_MIN, "minimal", job=_acp_job("pi"))
    assert locked.acp_user_entries is None
    assert "acp_user_entries" not in locked.canonical_payload()
    assert "acp_user_entries" not in locked_to_summary(locked).as_dict()


def test_user_entry_lock_stores_snapshot_and_changes_digest() -> None:
    _home_file(_kimi_doc())
    first = lock_task(CONFIG_MIN, "minimal", job=_acp_job("kimi"))
    assert first.acp_user_entries is not None
    snap = dict(first.acp_user_entries["kimi"])
    assert snap["entry_id"] == "kimi"
    assert snap["runtime"]["node"] == ">=18.0.0"
    blob = json.dumps(thaw(snap))
    for banned in ("install_command", "fixed_env", "source", "/Users", "/opt", "/home"):
        assert banned not in blob
    assert list(locked_to_summary(first).as_dict()["acp_user_entries"]) == ["kimi"]
    _home_file(
        _kimi_doc(
            acp_version="1.2.4",
            install_command="npm install -g @moonshot-ai/kimi-code@1.2.4",
        )
    )
    second = lock_task(CONFIG_MIN, "minimal", job=_acp_job("kimi"))
    assert second.digest != first.digest
    assert second.acp_user_entries is not None
    assert second.acp_user_entries["kimi"]["acp_version"] == "1.2.4"


def test_referenced_user_entries_are_sorted_and_skip_packaged_ids() -> None:
    doc = _kimi_doc()
    entries = doc["entries"]
    assert isinstance(entries, list)
    zeta = dict(entries[0])
    zeta["entry_id"] = "zeta"
    zeta["engine_detect_commands"] = ["zeta"]
    zeta["acp_detect_commands"] = ["zeta"]
    zeta["acp_command"] = ["zeta", "acp"]
    entries.append(zeta)
    _home_file(doc)
    snaps = referenced_acp_user_entries(
        [
            {"executor": "acp", "options": {"entry": "zeta"}},
            {"executor": "acp", "options": {"entry": "pi"}},
            {"executor": "acp", "options": {"entry": "kimi"}},
        ]
    )
    assert snaps is not None
    assert list(snaps) == ["kimi", "zeta"]


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
