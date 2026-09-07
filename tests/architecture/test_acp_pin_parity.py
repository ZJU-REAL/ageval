"""Pin parity: acp_entries.json ↔ contrib/docker/attempt/acp-entries.lock.json."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_host_registry_and_image_lock_pins_match() -> None:
    entries = json.loads(
        (REPO / "src/ageval/plugins/contrib/acp/acp_entries.json").read_text(encoding="utf-8")
    )
    lock = json.loads(
        (REPO / "src/ageval/plugins/contrib/docker/attempt/acp-entries.lock.json").read_text(
            encoding="utf-8"
        )
    )
    assert entries["python_sdk"]["version"] == lock["python_sdk"]["version"]
    by_id = {e["entry_id"]: e for e in entries["entries"]}
    for entry_id, row in lock["entries"].items():
        assert entry_id in by_id
        host = by_id[entry_id]
        assert host["acp_version"] == row["acp_entry"]["version"]
        if host.get("engine_version") is not None:
            assert host["engine_version"] == row["engine"]["version"]
        assert host["acp_command"] == row["acp_entry"]["command"]


def test_install_script_pins_match_lock() -> None:
    script = (REPO / "src/ageval/plugins/contrib/docker/attempt/install-executors.sh").read_text(
        encoding="utf-8"
    )
    lock = json.loads(
        (REPO / "src/ageval/plugins/contrib/docker/attempt/acp-entries.lock.json").read_text(
            encoding="utf-8"
        )
    )
    for _eid, row in lock["entries"].items():
        ver = row["acp_entry"]["version"]
        pkg = row["acp_entry"]["package"]
        if pkg:
            assert f"{pkg}@{ver}" in script or f'"{pkg}@{ver}"' in script
        eng = row["engine"].get("package")
        eng_ver = row["engine"].get("version")
        if eng and eng_ver:
            assert f"{eng}@{eng_ver}" in script
