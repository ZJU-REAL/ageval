"""Git-sourced Dataset refs: parse, eval_digest, sparse resolve (#305)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ageval.config.errors import ConfigError
from ageval.registry.cache import PackageCache
from ageval.registry.digest import compute_eval_digest
from ageval.registry.ref import parse_package_ref
from ageval.registry.resolve import resolve_dataset_root

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


def test_parse_github_ref() -> None:
    ref = parse_package_ref("github:org/repo@v1.0.0")
    assert ref.kind == "git"
    assert ref.git_url == "https://github.com/org/repo.git"
    assert ref.git_ref == "v1.0.0"
    assert ref.subdir is None


def test_parse_https_ref_with_subdir() -> None:
    ref = parse_package_ref("https://huggingface.co/datasets/org/name@v2#datasets/a")
    assert ref.kind == "git"
    assert ref.git_url == "https://huggingface.co/datasets/org/name"
    assert ref.git_ref == "v2"
    assert ref.subdir == "datasets/a"


@pytest.mark.parametrize(
    "raw",
    [
        "github:org/repo",
        "github:org/repo@main",
        "https://github.com/org/repo.git",
        "github:org/repo@v1#../escape",
        "github:org/repo@v1#datasets/../escape",
    ],
)
def test_parse_rejects_mutable_or_escaping_refs(raw: str) -> None:
    with pytest.raises(ConfigError) as exc:
        parse_package_ref(raw)
    assert exc.value.error_code == "invalid_package"


def _copy_dataset(dest: Path) -> Path:
    shutil.copytree(FIXTURE, dest)
    return dest


def test_eval_digest_ignores_readme_but_tracks_tests(tmp_path: Path) -> None:
    root = _copy_dataset(tmp_path / "ds")
    base = compute_eval_digest(root)
    (root / "README.md").write_text("# docs only\n", encoding="utf-8")
    assert compute_eval_digest(root) == base
    task_dir = root / "tasks" / "hello"
    (task_dir / "evaluation").mkdir(exist_ok=True)
    (task_dir / "evaluation" / "check.py").write_text("assert True\n", encoding="utf-8")
    assert compute_eval_digest(root) != base


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _make_remote(tmp_path: Path) -> Path:
    """Bare remote with two Datasets under datasets/a and datasets/b."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "T")
    for name in ("a", "b"):
        dest = work / "datasets" / name
        shutil.copytree(FIXTURE, dest)
        text = (dest / "ageval.yaml").read_text(encoding="utf-8")
        (dest / "ageval.yaml").write_text(
            text.replace("test/publish-min", f"test/ds-{name}"), encoding="utf-8"
        )
    (work / "README.md").write_text("root\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "init")
    _git(work, "tag", "v1.0.0")
    _git(work, "branch", "feature-x")
    remote = tmp_path / "remote.git"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(remote))
    return remote


def test_resolve_git_subdir_sparse_and_digest_scope(tmp_path: Path) -> None:
    remote = _make_remote(tmp_path)
    cache = PackageCache(tmp_path / "cache")
    root = resolve_dataset_root(f"file://{remote}@v1.0.0#datasets/a", cache=cache)
    assert (root / "ageval.yaml").is_file()
    digest_a = compute_eval_digest(root)

    # Editing sibling b in a new commit must not change a's digest: resolve b
    # only to prove both exist, then compare a fresh checkout of a.
    root_b = resolve_dataset_root(f"file://{remote}@v1.0.0#datasets/b", cache=cache)
    assert (root_b / "ageval.yaml").is_file()
    assert compute_eval_digest(root) == digest_a


def test_self_contained_rejects_escaping_symlink(tmp_path: Path) -> None:
    from ageval.registry.resolve import assert_self_contained

    root = _copy_dataset(tmp_path / "ds")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (root / "tasks" / "hello" / "escape").symlink_to(outside)
    with pytest.raises(ConfigError) as exc:
        assert_self_contained(root)
    assert exc.value.error_code == "invalid_package"


def test_resolve_git_branch_ref_fails(tmp_path: Path) -> None:
    remote = _make_remote(tmp_path)
    with pytest.raises(ConfigError) as exc:
        resolve_dataset_root(f"file://{remote}@feature-x", cache=PackageCache(tmp_path / "cache"))
    assert exc.value.error_code == "invalid_package"


def test_lock_records_resolved_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from typer.testing import CliRunner

    from ageval.cli.main import app

    remote = _make_remote(tmp_path)
    monkeypatch.setenv("AGEVAL_CACHE_ROOT", str(tmp_path / "cache"))
    result = CliRunner().invoke(
        app, ["lock", f"file://{remote}@v1.0.0#datasets/a", "--task", "hello"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    commit = payload["source"]["commit"]
    assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
    assert payload["source"]["subdir"] == "datasets/a"
    assert payload["eval_digest"].startswith("sha256:")


def test_lock_from_cache_root_records_source(tmp_path: Path) -> None:
    """Suite runs lock the resolved cache root; the marker restores source."""
    import json

    from typer.testing import CliRunner

    from ageval.cli.main import app

    remote = _make_remote(tmp_path)
    cache = PackageCache(tmp_path / "cache")
    root = resolve_dataset_root(f"file://{remote}@v1.0.0#datasets/a", cache=cache)
    result = CliRunner().invoke(app, ["lock", str(root), "--task", "hello"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"]["git_url"].startswith("file://")
    assert len(payload["source"]["commit"]) == 40


def test_resolve_git_subdir_without_manifest_fails(tmp_path: Path) -> None:
    remote = _make_remote(tmp_path)
    with pytest.raises(ConfigError) as exc:
        resolve_dataset_root(
            f"file://{remote}@v1.0.0#datasets/nope", cache=PackageCache(tmp_path / "cache")
        )
    assert exc.value.error_code == "invalid_package"
