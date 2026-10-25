"""Incremental workspace checkpoints and sealed-attempt pruning."""

from __future__ import annotations

import os
from pathlib import Path

from ageval.evidence.checkpoints import (
    CHECKPOINT_FORMAT,
    CheckpointStore,
    prune_checkpoints,
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


def test_prune_removes_checkpoint_dir(tmp_path: Path) -> None:
    box = _box(tmp_path)
    (box / "workspace" / "note.txt").write_text("x", encoding="utf-8")
    CheckpointStore(tmp_path, box).capture(1)
    prune_checkpoints(tmp_path)
    assert not (tmp_path / "checkpoints").exists()
    assert (box / "workspace" / "note.txt").is_file()
