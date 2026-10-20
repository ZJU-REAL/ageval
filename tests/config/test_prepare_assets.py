"""Declarative assets + gated prepare step (#306)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ageval.cli.main import app
from ageval.config.dataset import load_dataset_manifest
from ageval.config.errors import ConfigError
from ageval.config.prepare import prepare_dataset
from ageval.registry.digest import compute_eval_digest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"

CONTENT = b"clip-bytes"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dataset(
    tmp_path: Path,
    *,
    assets: list[dict[str, str]] | None = None,
    prepare: str | None = None,
    script: str | None = None,
    extra_root: str = "",
) -> Path:
    root = tmp_path / "ds"
    shutil.copytree(FIXTURE, root)
    lines = (root / "ageval.yaml").read_text(encoding="utf-8")
    if assets:
        lines += "assets:\n"
        for a in assets:
            lines += f"  - path: {a['path']}\n    url: {a['url']}\n    sha256: {a['sha256']}\n"
    if prepare:
        lines += f"prepare: {prepare}\n"
    if extra_root:
        lines += extra_root
    (root / "ageval.yaml").write_text(lines, encoding="utf-8")
    if script is not None:
        (root / "prepare.sh").write_text(script, encoding="utf-8")
    return root


def _asset(tmp_path: Path, url_path: Path) -> dict[str, str]:
    return {
        "path": "tasks/hello/data/clip.bin",
        "url": url_path.as_uri(),
        "sha256": _sha(CONTENT),
    }


def test_manifest_parses_assets_and_prepare(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(CONTENT)
    root = _dataset(
        tmp_path, assets=[_asset(tmp_path, src)], prepare="./prepare.sh", script="true\n"
    )
    man = load_dataset_manifest(root)
    assert man.assets[0].path == "tasks/hello/data/clip.bin"
    assert man.prepare == "prepare.sh"


def test_prepare_downloads_then_skips(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(CONTENT)
    root = _dataset(tmp_path, assets=[_asset(tmp_path, src)])
    report = prepare_dataset(root)
    dest = root / "tasks" / "hello" / "data" / "clip.bin"
    assert dest.read_bytes() == CONTENT
    assert report.downloaded == ("tasks/hello/data/clip.bin",)
    again = prepare_dataset(root)
    assert again.skipped == ("tasks/hello/data/clip.bin",)
    assert again.downloaded == ()


def test_prepare_digest_mismatch_stops(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(b"other")
    root = _dataset(tmp_path, assets=[_asset(tmp_path, src)])
    with pytest.raises(ConfigError) as exc:
        prepare_dataset(root)
    assert exc.value.error_code == "asset_digest_mismatch"
    assert not (root / "tasks" / "hello" / "data" / "clip.bin").exists()


def test_prepare_download_failure_code(tmp_path: Path) -> None:
    asset = _asset(tmp_path, tmp_path / "missing.bin")
    root = _dataset(tmp_path, assets=[asset])
    with pytest.raises(ConfigError) as exc:
        prepare_dataset(root)
    assert exc.value.error_code == "asset_download_failed"


def test_prepare_script_gated_by_default(tmp_path: Path) -> None:
    root = _dataset(tmp_path, prepare="./prepare.sh", script="touch made.txt\n")
    with pytest.raises(ConfigError) as exc:
        prepare_dataset(root)
    assert exc.value.error_code == "prepare_not_allowed"
    assert not (root / "made.txt").exists()


def test_prepare_script_runs_with_allow_and_via_trust_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _dataset(tmp_path, prepare="./prepare.sh", script="touch made.txt\n")
    report = prepare_dataset(root, allow_prepare=True)
    assert report.prepare_ran is True
    assert (root / "made.txt").is_file()
    # Second call is a no-op via the prepare marker.
    assert prepare_dataset(root, allow_prepare=True).prepare_ran is False


def test_prepare_trust_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sub = tmp_path / "second"
    sub.mkdir()
    root = _dataset(sub, prepare="./prepare.sh", script="touch made.txt\n")
    monkeypatch.setenv("AGEVAL_PREPARE_TRUST", "test/publish-min")
    report = prepare_dataset(root)
    assert report.prepare_ran is True


def test_prepare_script_still_verifies_assets(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(CONTENT)
    root = _dataset(
        tmp_path,
        assets=[_asset(tmp_path, src)],
        prepare="./prepare.sh",
        script="echo corrupt > tasks/hello/data/clip.bin\n",
    )
    with pytest.raises(ConfigError) as exc:
        prepare_dataset(root, allow_prepare=True)
    assert exc.value.error_code == "asset_digest_mismatch"


def test_eval_digest_ignores_downloaded_asset_content(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(CONTENT)
    root = _dataset(tmp_path, assets=[_asset(tmp_path, src)])
    before = compute_eval_digest(root)
    prepare_dataset(root)
    assert compute_eval_digest(root) == before


def test_cli_prepare_command(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(CONTENT)
    root = _dataset(tmp_path, assets=[_asset(tmp_path, src)])
    result = CliRunner().invoke(app, ["prepare", str(root)])
    assert result.exit_code == 0, result.output
    assert (root / "tasks" / "hello" / "data" / "clip.bin").is_file()


def test_lock_carries_prepare_gate(tmp_path: Path) -> None:
    root = _dataset(tmp_path, prepare="./prepare.sh", script="true\n")
    result = CliRunner().invoke(app, ["lock", str(root), "--task", "hello"])
    assert result.exit_code == 2
    assert "prepare_not_allowed" in result.output
    ok = CliRunner().invoke(app, ["lock", str(root), "--task", "hello", "--allow-prepare"])
    assert ok.exit_code == 0, ok.output


def test_manifest_rejects_escaping_asset(tmp_path: Path) -> None:
    root = _dataset(
        tmp_path,
        assets=[{"path": "../escape.bin", "url": "https://x/y", "sha256": _sha(b"z")}],
    )
    with pytest.raises(ConfigError):
        load_dataset_manifest(root)
