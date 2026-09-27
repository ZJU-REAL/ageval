"""Attempt/suite result archives exclude l1-work residual (issue #76)."""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

from ageval.registry.results_archive import build_attempt_archive, build_suite_archive


def _arcnames(archive: bytes) -> set[str]:
    with (
        gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb") as gz,
        tarfile.open(fileobj=gz, mode="r:") as tar,
    ):
        return {m.name for m in tar.getmembers() if m.isfile()}


def test_build_attempt_archive_excludes_l1_work(tmp_path: Path) -> None:
    run_id = "run_test76"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "result.json").write_text('{"status":"PASS"}\n', encoding="utf-8")
    (run_dir / "lock.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "agent").mkdir()
    (run_dir / "agent" / "trajectory.jsonl").write_text("{}\n", encoding="utf-8")
    work = run_dir / "l1-work"
    (work / "workspace").mkdir(parents=True)
    (work / "workspace" / "scratch.txt").write_text("do not upload\n", encoding="utf-8")
    (work / "package_view").mkdir()
    (work / "package_view" / "vendor.bin").write_bytes(b"x" * 32)

    archive, digest, size = build_attempt_archive(run_dir, run_id=run_id)
    assert size == len(archive)
    assert digest.startswith("sha256:")

    names = _arcnames(archive)
    prefix = f".ageval/runs/{run_id}"
    assert f"{prefix}/result.json" in names
    assert f"{prefix}/lock.json" in names
    assert f"{prefix}/agent/trajectory.jsonl" in names
    assert not any("l1-work" in n for n in names)


def test_build_suite_archive_excludes_nested_l1_work(tmp_path: Path) -> None:
    suite_id = "suite_test76"
    suite_dir = tmp_path / suite_id
    suite_dir.mkdir()
    (suite_dir / "summary.json").write_text("{}\n", encoding="utf-8")
    nested = suite_dir / "nested" / "l1-work" / "workspace"
    nested.mkdir(parents=True)
    (nested / "leak.txt").write_text("nope\n", encoding="utf-8")

    (suite_dir / "live-share.json").write_text('{"token":"capability"}\n', encoding="utf-8")

    archive, _, _ = build_suite_archive(suite_dir, suite_run_id=suite_id)
    names = _arcnames(archive)
    assert f".ageval/suite-runs/{suite_id}/summary.json" in names
    assert not any("l1-work" in n for n in names)
    assert not any("live-share.json" in n for n in names)
