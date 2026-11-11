"""ageval view accepts a registry ref and opens a verified cache tree."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ageval.cli.main import app
from ageval.registry.cache import PackageCache
from ageval.registry.resolve import resolve_dataset_root

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"
DIGEST = "sha256:" + ("a" * 64)


class _BoomClient:
    def get_metadata(self, **_kwargs: object) -> object:
        raise AssertionError("version cache hit must not contact the registry")


def _plant_cache(cache_root: Path) -> Path:
    cache = PackageCache(cache_root)
    dest = cache.entry_dir("test/suite-min", DIGEST)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SUITE, dest, ignore=shutil.ignore_patterns(".ageval"))
    (dest / ".ageval-verified").write_text(
        json.dumps(
            {
                "schema": "ageval.cache.verified/1",
                "dataset_id": "test/suite-min",
                "package_digest": DIGEST,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return dest


def test_view_help_names_registry_ref() -> None:
    result = CliRunner().invoke(app, ["view", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "registry ref" in result.stdout.lower()
    assert "@" in result.stdout


def test_upload_suite_help_names_registry_ref() -> None:
    result = CliRunner().invoke(app, ["results", "upload-suite", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "registry ref" in result.stdout.lower()
    assert "@" in result.stdout


def test_resolve_version_hits_verified_cache(tmp_path: Path) -> None:
    planted = _plant_cache(tmp_path / "cache")
    got = resolve_dataset_root(
        "test/suite-min@0.1.0",
        cache=PackageCache(tmp_path / "cache"),
        client=_BoomClient(),  # type: ignore[arg-type]
    )
    assert got == planted


def test_lookup_version_none_when_ambiguous(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    _plant_cache(cache_root)
    other = DIGEST[:-1] + "b"
    dest = PackageCache(cache_root).entry_dir("test/suite-min", other)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SUITE, dest, ignore=shutil.ignore_patterns(".ageval"))
    (dest / ".ageval-verified").write_text(
        json.dumps(
            {
                "schema": "ageval.cache.verified/1",
                "dataset_id": "test/suite-min",
                "package_digest": other,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    assert PackageCache(cache_root).lookup_version("test/suite-min", "0.1.0") is None


def test_open_dataset_version_ref_uses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ageval.viewer import browse

    planted = _plant_cache(tmp_path / "cache")
    monkeypatch.setenv("AGEVAL_CACHE_ROOT", str(tmp_path / "cache"))
    assert browse.open_dataset("test/suite-min@0.1.0") == planted.resolve()
