"""Incremental workspace checkpoints and sealed-attempt pruning."""

from __future__ import annotations

import errno
import json
import os
import stat
from pathlib import Path

import pytest

from ageval.evidence.checkpoints import (
    CHECKPOINT_FORMAT,
    CheckpointStore,
    prune_checkpoints,
    prune_recovery_bundle,
    prune_recovery_state,
)


def _box(tmp_path: Path) -> Path:
    box = tmp_path / "box"
    (box / "workspace").mkdir(parents=True)
    (box / "home").mkdir()
    (box / "artifacts").mkdir()
    return box


def test_capture_is_incremental_and_skips_keyless_auth(tmp_path: Path) -> None:
    box = _box(tmp_path)
    workspace = box / "workspace" / "note.txt"
    workspace.write_text("one", encoding="utf-8")
    auth = box / "home" / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text('{"token":"secret"}', encoding="utf-8")
    store = CheckpointStore(tmp_path, box)
    first = store.capture(2)
    manifest = first.read_text(encoding="utf-8")
    assert CHECKPOINT_FORMAT in manifest
    assert "note.txt" in manifest
    assert "auth.json" not in manifest
    blobs = list((tmp_path / "checkpoints" / "blobs").rglob("*"))
    blob_files = [path for path in blobs if path.is_file()]
    assert len(blob_files) == 1

    second = store.capture(3)
    blob_files = [
        path for path in (tmp_path / "checkpoints" / "blobs").rglob("*") if path.is_file()
    ]
    assert len(blob_files) == 1
    assert second.name == "seq_000003.json"

    workspace.write_text("two", encoding="utf-8")
    store.capture(4)
    blob_files = [
        path for path in (tmp_path / "checkpoints" / "blobs").rglob("*") if path.is_file()
    ]
    assert len(blob_files) == 2


def test_home_journal_is_redacted_and_workspace_is_not(tmp_path: Path) -> None:
    box = _box(tmp_path)
    secret = "sk-abcdefghijklmnop"
    (box / "home" / "notes.txt").write_text(f"remember {secret}\n", encoding="utf-8")
    (box / "workspace" / "task.txt").write_text(f"keep {secret}\n", encoding="utf-8")
    auth = box / "home" / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text('{"token":"secret"}', encoding="utf-8")
    binary = box / "home" / "blob.bin"
    binary.write_bytes(b"\x00" + secret.encode("ascii"))
    store = CheckpointStore(tmp_path, box, sentinels=("SENTINELVALUE",))
    (box / "home" / "marked.txt").write_text("see SENTINELVALUE\n", encoding="utf-8")
    manifest_path = store.capture(2)
    blobs = tmp_path / "checkpoints" / "blobs"
    blob_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in blobs.rglob("*")
        if path.is_file() and "notes" not in path.name
    )
    # The secret from home text must not survive in any home blob.
    home_blobs = []
    manifest = manifest_path.read_text(encoding="utf-8")
    assert "auth.json" not in manifest
    assert secret not in manifest
    assert "home/blob.bin" in store.redaction_notes
    assert "home/blob.bin" not in manifest
    for path in blobs.rglob("*"):
        if path.is_file():
            home_blobs.append(path.read_bytes())
    joined = b"".join(home_blobs)
    assert secret.encode("ascii") not in joined or b"keep " + secret.encode("ascii") in joined
    # Workspace copy is intact. Home notes are not.
    assert b"keep " + secret.encode("ascii") in joined
    assert b"remember " + secret.encode("ascii") not in joined
    assert b"SENTINELVALUE" not in joined
    store.restore(2)
    restored = (box / "home" / "notes.txt").read_text(encoding="utf-8")
    assert secret not in restored
    assert "REDACTED" in restored
    assert (box / "workspace" / "task.txt").read_text(encoding="utf-8") == f"keep {secret}\n"
    del blob_text


def test_restore_rolls_back_files_and_deletes_extras(tmp_path: Path) -> None:
    box = _box(tmp_path)
    note = box / "workspace" / "note.txt"
    note.write_text("kept", encoding="utf-8")
    os.chmod(note, 0o640)
    store = CheckpointStore(tmp_path, box)
    store.capture(6)
    note.write_text("changed", encoding="utf-8")
    extra = box / "workspace" / "nested" / "extra.txt"
    extra.parent.mkdir()
    extra.write_text("gone", encoding="utf-8")
    store.restore(6)
    assert note.read_text(encoding="utf-8") == "kept"
    assert not extra.exists()
    assert not extra.parent.exists()
    assert note.stat().st_mode & 0o777 == 0o640


def _manifest(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_capture_omits_an_unreadable_file_and_keeps_its_mode(tmp_path: Path) -> None:
    box = _box(tmp_path)
    note = box / "workspace" / "note.txt"
    note.write_text("kept", encoding="utf-8")
    secret = box / "home" / "secret.txt"
    secret.write_text("hidden", encoding="utf-8")
    secret.chmod(0)
    mode = secret.stat().st_mode
    uid = secret.stat().st_uid
    try:
        manifest = _manifest(CheckpointStore(tmp_path, box).capture(1))
        assert secret.stat().st_mode == mode
        assert secret.stat().st_uid == uid
    finally:
        secret.chmod(0o644)
    entries = manifest["entries"]
    assert isinstance(entries, dict)
    assert "workspace/note.txt" in entries
    assert "home/secret.txt" not in entries


def test_capture_omits_an_unreadable_directory(tmp_path: Path) -> None:
    box = _box(tmp_path)
    (box / "workspace" / "note.txt").write_text("kept", encoding="utf-8")
    visible = box / "home" / "visible.txt"
    visible.write_text("yes", encoding="utf-8")
    private = box / "home" / "private"
    private.mkdir()
    hidden = private / "hidden.txt"
    hidden.write_text("nope", encoding="utf-8")
    private.chmod(0)
    mode = private.stat().st_mode
    try:
        manifest = _manifest(CheckpointStore(tmp_path, box).capture(1))
        assert private.stat().st_mode == mode
    finally:
        private.chmod(0o755)
    entries = manifest["entries"]
    assert isinstance(entries, dict)
    assert "workspace/note.txt" in entries
    assert "home/visible.txt" in entries
    assert "home/private/hidden.txt" not in entries


def test_capture_omits_a_stat_permission_error(tmp_path: Path, monkeypatch) -> None:
    box = _box(tmp_path)
    (box / "workspace" / "note.txt").write_text("kept", encoding="utf-8")
    secret = box / "home" / "secret.txt"
    secret.write_text("hidden", encoding="utf-8")
    mode = secret.stat().st_mode
    original = Path.stat

    def stat_path(self: Path, *args, **kwargs):  # noqa: ANN002, ANN003
        if self.name == "secret.txt":
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_path)
    manifest = _manifest(CheckpointStore(tmp_path, box).capture(1))
    entries = manifest["entries"]
    assert isinstance(entries, dict)
    assert "workspace/note.txt" in entries
    assert "home/secret.txt" not in entries
    assert original(secret).st_mode == mode


def test_capture_omits_an_entry_probe_permission_error(tmp_path: Path, monkeypatch) -> None:
    box = _box(tmp_path)
    (box / "workspace" / "note.txt").write_text("kept", encoding="utf-8")
    secret = box / "home" / "secret.txt"
    secret.write_text("hidden", encoding="utf-8")
    mode = secret.stat().st_mode
    original = Path.lstat

    def lstat_path(self: Path, *args, **kwargs):  # noqa: ANN002, ANN003
        if self.name == "secret.txt":
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat_path)
    manifest = _manifest(CheckpointStore(tmp_path, box).capture(1))
    entries = manifest["entries"]
    assert isinstance(entries, dict)
    assert "workspace/note.txt" in entries
    assert "home/secret.txt" not in entries
    assert stat.S_IMODE(secret.stat().st_mode) == stat.S_IMODE(mode)


def test_capture_propagates_a_non_permission_read_error(tmp_path: Path, monkeypatch) -> None:
    box = _box(tmp_path)
    (box / "workspace" / "note.txt").write_text("kept", encoding="utf-8")
    (box / "home" / "secret.txt").write_text("hidden", encoding="utf-8")
    original = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        if self.name == "secret.txt":
            raise OSError(errno.EIO, "Input/output error", str(self))
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    with pytest.raises(OSError) as raised:
        CheckpointStore(tmp_path, box).capture(1)
    assert raised.value.errno == errno.EIO


def test_capture_propagates_a_non_permission_stat_error(tmp_path: Path, monkeypatch) -> None:
    box = _box(tmp_path)
    (box / "workspace" / "note.txt").write_text("kept", encoding="utf-8")
    (box / "home" / "secret.txt").write_text("hidden", encoding="utf-8")
    original = Path.stat

    def stat_path(self: Path, *args, **kwargs):  # noqa: ANN002, ANN003
        if self.name == "secret.txt":
            raise OSError(errno.EIO, "Input/output error", str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_path)
    with pytest.raises(OSError) as raised:
        CheckpointStore(tmp_path, box).capture(1)
    assert raised.value.errno == errno.EIO


def test_capture_propagates_a_non_permission_entry_probe(tmp_path: Path, monkeypatch) -> None:
    box = _box(tmp_path)
    (box / "workspace" / "note.txt").write_text("kept", encoding="utf-8")
    (box / "home" / "secret.txt").write_text("hidden", encoding="utf-8")
    original = Path.lstat

    def lstat_path(self: Path, *args, **kwargs):  # noqa: ANN002, ANN003
        if self.name == "secret.txt":
            raise OSError(errno.EIO, "Input/output error", str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat_path)
    with pytest.raises(OSError) as raised:
        CheckpointStore(tmp_path, box).capture(1)
    assert raised.value.errno == errno.EIO


def test_capture_propagates_a_non_permission_directory_list_error(
    tmp_path: Path, monkeypatch
) -> None:
    box = _box(tmp_path)
    (box / "workspace" / "note.txt").write_text("kept", encoding="utf-8")
    real_scandir = os.scandir

    def scandir(path):  # noqa: ANN001
        if Path(path).name == "workspace":
            raise OSError(errno.EIO, "Input/output error", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    with pytest.raises(OSError) as raised:
        CheckpointStore(tmp_path, box).capture(1)
    assert raised.value.errno == errno.EIO


def test_capture_skips_a_file_removed_during_the_scan(tmp_path: Path, monkeypatch) -> None:
    box = _box(tmp_path)
    (box / "workspace" / "note.txt").write_text("kept", encoding="utf-8")
    gone = box / "home" / "gone.txt"
    gone.write_text("temp", encoding="utf-8")
    original = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        if self.name == "gone.txt":
            gone.unlink()
            raise FileNotFoundError(gone)
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    manifest = json.loads(CheckpointStore(tmp_path, box).capture(1).read_text(encoding="utf-8"))
    assert "workspace/note.txt" in manifest["entries"]
    assert "home/gone.txt" not in manifest["entries"]


def test_prune_removes_checkpoint_dir(tmp_path: Path) -> None:
    box = _box(tmp_path)
    (box / "workspace" / "note.txt").write_text("x", encoding="utf-8")
    CheckpointStore(tmp_path, box).capture(1)
    state = tmp_path / "state"
    state.mkdir()
    (state / "nonce").write_text("n", encoding="utf-8")
    prune_checkpoints(tmp_path)
    prune_recovery_state(tmp_path)
    assert not (tmp_path / "checkpoints").exists()
    assert not state.exists()
    assert (box / "workspace" / "note.txt").is_file()


def test_prune_recovery_bundle_keeps_state_and_box(tmp_path: Path) -> None:
    box = _box(tmp_path)
    (box / "workspace" / "note.txt").write_text("x", encoding="utf-8")
    CheckpointStore(tmp_path, box).capture(1)
    (tmp_path / "activity.jsonl").write_text("{}\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    (state / "nonce").write_text("n", encoding="utf-8")
    (tmp_path / "result.json").write_text("{}", encoding="utf-8")
    (tmp_path / "trajectory.jsonl").write_text("{}\n", encoding="utf-8")

    prune_recovery_bundle(tmp_path)

    assert not (tmp_path / "checkpoints").exists()
    assert not (tmp_path / "activity.jsonl").exists()
    assert state.is_dir()
    assert (box / "workspace" / "note.txt").is_file()
    assert (tmp_path / "result.json").is_file()
