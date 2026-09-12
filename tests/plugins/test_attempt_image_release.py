"""GHCR Attempt job planner: skip / retag / rebuild from bake inputs."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "attempt_image_release.py"
WORKFLOW = ROOT / ".github" / "workflows" / "release-images.yml"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("attempt_image_release", SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


mod = _load()


def _files(payload: dict[str, str] | None = None) -> dict[str, bytes | None]:
    body: dict[str, bytes | None] = {
        relpath: f"{relpath}\n".encode() for relpath in mod.BAKE_RELPATHS
    }
    if payload:
        for relpath, text in payload.items():
            body[relpath] = text.encode()
    return body


def _digest(python_version: str = "3.12", payload: dict[str, str] | None = None) -> str:
    return mod.bake_digest(_files(payload), python_version)


def _inspect_map(mapping: dict[str, str]) -> Callable[[str], str]:
    def inspect(version: str) -> str:
        return mapping.get(version, "missing")

    return inspect


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_AUTHOR_NAME": "ageval",
            "GIT_AUTHOR_EMAIL": "ageval@example.com",
            "GIT_COMMITTER_NAME": "ageval",
            "GIT_COMMITTER_EMAIL": "ageval@example.com",
        }
    )
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "ageval@example.com")
    _git(repo, "config", "user.name", "ageval")
    return repo


def _write_bake(
    repo: Path,
    *,
    python_version: str = "3.12",
    extra: dict[str, str] | None = None,
) -> None:
    for relpath in (
        *mod.BAKE_RELPATHS,
        mod.WORKFLOW_PATH,
        "src/ageval/plugins/contrib/docker/attempt/build.py",
    ):
        path = repo / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        if relpath == mod.WORKFLOW_PATH:
            path.write_text(
                "jobs:\n  attempt:\n    env:\n"
                f'      ATTEMPT_PYTHON_VERSION: "{python_version}"\n'
                "          build-args: |\n"
                f"            PYTHON_VERSION={python_version}\n",
                encoding="utf-8",
            )
            continue
        if extra and relpath in extra:
            path.write_text(extra[relpath], encoding="utf-8")
        else:
            path.write_text(f"{relpath}\n", encoding="utf-8")


def _commit_tag(repo: Path, version: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"release {version}")
    _git(repo, "tag", f"v{version}")


def test_bake_paths_are_copied_into_the_image_not_parent_helpers() -> None:
    names = {Path(relpath).name for relpath in mod.BAKE_RELPATHS}
    assert names == {
        "Dockerfile",
        "install-executors.sh",
        "acp-entries.lock.json",
        "sitecustomize.py",
    }
    assert all(relpath.startswith(f"{mod.ATTEMPT_DIR}/") for relpath in mod.BAKE_RELPATHS)
    assert "build.py" not in names
    assert "__init__.py" not in names


def test_bake_digest_tracks_pins_sitecustomize_and_python_version() -> None:
    base = _digest()
    assert base != _digest(payload={f"{mod.ATTEMPT_DIR}/install-executors.sh": "pin-b\n"})
    assert base != _digest(payload={f"{mod.ATTEMPT_DIR}/acp-entries.lock.json": "{}\n"})
    assert base != _digest(payload={f"{mod.ATTEMPT_DIR}/sitecustomize.py": "print(1)\n"})
    assert base != _digest(python_version="3.13")
    assert base == _digest()


def test_parent_only_build_py_is_not_a_bake_input() -> None:
    base = _digest()
    files = _files()
    files["src/ageval/plugins/contrib/docker/attempt/build.py"] = b"changed helper\n"
    assert mod.bake_digest(files, "3.12") == base


def test_parse_release_tag_rejects_prerelease() -> None:
    assert mod.parse_release_tag("v0.8.0") == "0.8.0"
    assert mod.parse_release_tag("0.8.0") is None
    assert mod.parse_release_tag("v0.8.0-rc1") is None
    assert mod.parse_release_tag("v0.8") is None
    assert mod.normalize_version("v1.2.3") == "1.2.3"
    assert mod.normalize_version("1.2.3") == "1.2.3"
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        mod.normalize_version("v1.2.3-rc1")


def test_older_release_versions_are_strictly_less_and_newest_first() -> None:
    assert mod.older_release_versions(["0.9.0", "0.8.1", "0.8.0", "0.7.3"], "0.8.1") == [
        "0.8.0",
        "0.7.3",
    ]


def test_skip_when_this_version_tag_already_exists() -> None:
    decision = mod.decide(
        version="0.8.1",
        force_rebuild=False,
        head_digest=_digest(),
        previous_versions=["0.8.0"],
        inspect=_inspect_map({"0.8.1": "exists", "0.8.0": "exists"}),
        digest_for=lambda _version: _digest(),
    )
    assert decision.action == "skip"
    assert decision.reason == "version_tag_exists"


def test_force_rebuild_overrides_existing_tag() -> None:
    decision = mod.decide(
        version="0.8.1",
        force_rebuild=True,
        head_digest=_digest(),
        previous_versions=["0.8.0"],
        inspect=_inspect_map({"0.8.1": "exists", "0.8.0": "exists"}),
        digest_for=lambda _version: _digest(),
    )
    assert decision.action == "rebuild"
    assert decision.reason == "force_rebuild"


def test_retag_when_inputs_match_previous_published_image() -> None:
    digest = _digest()
    decision = mod.decide(
        version="v0.8.1",
        force_rebuild=False,
        head_digest=digest,
        previous_versions=["0.8.0", "0.7.3"],
        inspect=_inspect_map({"0.8.0": "exists", "0.7.3": "exists"}),
        digest_for=lambda _version: digest,
    )
    assert decision.action == "retag"
    assert decision.reason == "inputs_unchanged"
    assert decision.source_version == "0.8.0"
    assert decision.source_ref == f"{mod.ATTEMPT_IMAGE}:0.8.0"


def test_rebuild_when_pins_change_even_if_dockerfile_matches() -> None:
    head = _digest(payload={f"{mod.ATTEMPT_DIR}/install-executors.sh": "new-pin\n"})
    previous = _digest()
    decision = mod.decide(
        version="0.8.1",
        force_rebuild=False,
        head_digest=head,
        previous_versions=["0.8.0"],
        inspect=_inspect_map({"0.8.0": "exists"}),
        digest_for=lambda _version: previous,
    )
    assert decision.action == "rebuild"
    assert decision.reason == "inputs_changed"


def test_walk_past_missing_ghcr_tag_to_older_published_image() -> None:
    digest = _digest()
    decision = mod.decide(
        version="0.8.1",
        force_rebuild=False,
        head_digest=digest,
        previous_versions=["0.8.0", "0.7.3"],
        inspect=_inspect_map({"0.8.0": "missing", "0.7.3": "exists"}),
        digest_for=lambda _version: digest,
    )
    assert decision.action == "retag"
    assert decision.source_version == "0.7.3"


def test_inspect_error_on_previous_tag_rebuilds() -> None:
    decision = mod.decide(
        version="0.8.1",
        force_rebuild=False,
        head_digest=_digest(),
        previous_versions=["0.8.0"],
        inspect=_inspect_map({"0.8.0": "error"}),
        digest_for=lambda _version: _digest(),
    )
    assert decision.action == "rebuild"
    assert decision.reason == "inspect_failed"


def test_inspect_error_on_current_tag_rebuilds() -> None:
    decision = mod.decide(
        version="0.8.1",
        force_rebuild=False,
        head_digest=_digest(),
        previous_versions=["0.8.0"],
        inspect=_inspect_map({"0.8.1": "error", "0.8.0": "exists"}),
        digest_for=lambda _version: _digest(),
    )
    assert decision.action == "rebuild"
    assert decision.reason == "inspect_failed"


def test_first_tag_or_no_previous_image_rebuilds() -> None:
    decision = mod.decide(
        version="0.1.0",
        force_rebuild=False,
        head_digest=_digest(),
        previous_versions=[],
        inspect=_inspect_map({}),
        digest_for=lambda _version: _digest(),
    )
    assert decision.action == "rebuild"
    assert decision.reason == "no_previous_image"


def test_classify_inspect_distinguishes_not_found_from_error() -> None:
    assert mod.classify_inspect(0, "") == "exists"
    assert mod.classify_inspect(1, "ERROR: manifest unknown") == "missing"
    assert (
        mod.classify_inspect(1, "name unknown: ghcr.io/zju-real/ageval-attempt:0.8.0") == "missing"
    )
    assert mod.classify_inspect(1, "failed to authorize: denied") == "error"


def test_inspect_ghcr_classifies_not_found_on_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["docker"],
            returncode=1,
            stdout="ERROR: manifest unknown\n",
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.inspect_ghcr(mod.ATTEMPT_IMAGE, "0.8.0") == "missing"


def test_workflow_python_version_reads_job_build_arg() -> None:
    assert mod.workflow_python_version(WORKFLOW.read_text(encoding="utf-8")) == "3.12"
    assert (
        mod.workflow_python_version('ATTEMPT_PYTHON_VERSION: "3.13"\nPYTHON_VERSION=3.12\n')
        == "3.12"
    )


def test_github_output_is_stable_tokens() -> None:
    text = mod.Decision(
        action="retag",
        reason="inputs_unchanged",
        source_version="0.8.0",
        source_ref="ghcr.io/zju-real/ageval-attempt:0.8.0",
    ).as_github_output()
    assert text == (
        "action=retag\n"
        "reason=inputs_unchanged\n"
        "source_version=0.8.0\n"
        "source_ref=ghcr.io/zju-real/ageval-attempt:0.8.0\n"
    )


def test_plan_from_git_retags_unchanged_inputs(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_bake(repo)
    _commit_tag(repo, "0.8.0")
    (repo / "src/ageval/plugins/contrib/docker/attempt/build.py").write_text(
        "parent helper only\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "docs-only helper")
    _git(repo, "tag", "v0.8.1")
    decision = mod.plan_from_git(
        repo,
        version="0.8.1",
        python_version="3.12",
        force_rebuild=False,
        inspect=_inspect_map({"0.8.0": "exists"}),
    )
    assert decision.action == "retag"
    assert decision.source_version == "0.8.0"


def test_plan_from_git_skips_when_version_tag_exists(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_bake(repo)
    _commit_tag(repo, "0.8.0")
    _git(repo, "tag", "v0.8.1")
    decision = mod.plan_from_git(
        repo,
        version="0.8.1",
        python_version="3.12",
        force_rebuild=False,
        inspect=_inspect_map({"0.8.1": "exists", "0.8.0": "exists"}),
    )
    assert decision.action == "skip"
    assert decision.reason == "version_tag_exists"


def test_plan_from_git_rebuilds_when_python_version_changes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_bake(repo, python_version="3.12")
    _commit_tag(repo, "0.8.0")
    _write_bake(repo, python_version="3.13")
    _commit_tag(repo, "0.8.1")
    decision = mod.plan_from_git(
        repo,
        version="0.8.1",
        python_version="3.13",
        force_rebuild=False,
        inspect=_inspect_map({"0.8.0": "exists"}),
    )
    assert decision.action == "rebuild"
    assert decision.reason == "inputs_changed"


def test_plan_from_git_rebuilds_when_lock_changes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_bake(repo)
    _commit_tag(repo, "0.8.0")
    lock = repo / f"{mod.ATTEMPT_DIR}/acp-entries.lock.json"
    lock.write_text('{"pin": 2}\n', encoding="utf-8")
    _commit_tag(repo, "0.8.1")
    decision = mod.plan_from_git(
        repo,
        version="0.8.1",
        python_version="3.12",
        force_rebuild=False,
        inspect=_inspect_map({"0.8.0": "exists"}),
    )
    assert decision.action == "rebuild"
    assert decision.reason == "inputs_changed"


def test_cli_writes_github_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path)
    _write_bake(repo)
    _commit_tag(repo, "0.8.0")
    _git(repo, "tag", "v0.8.1")
    out = tmp_path / "github.out"
    monkeypatch.setattr(
        mod, "inspect_ghcr", lambda _image, version: "exists" if version == "0.8.0" else "missing"
    )
    code = mod.main(
        [
            "--version",
            "v0.8.1",
            "--repo",
            str(repo),
            "--github-output",
            str(out),
        ]
    )
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "action=retag\n" in text
    assert "source_version=0.8.0\n" in text


def test_release_images_workflow_wires_content_aware_attempt_job() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    header, jobs = text.split("jobs:", 1)
    assert "paths:" not in header
    assert "scripts/attempt_image_release.py" in jobs
    assert "imagetools create" in jobs
    assert "fetch-depth: 0" in jobs
    assert "fetch-tags: true" in jobs
    assert "force_rebuild" in header
    assert "ghcr.io/zju-real/ageval-attempt" in jobs
    assert "linux/amd64,linux/arm64" in jobs
    assert 'ATTEMPT_PYTHON_VERSION: "3.12"' in jobs
    assert "steps.plan.outputs.action == 'rebuild'" in jobs
    assert "steps.plan.outputs.action == 'retag'" in jobs
    assert "steps.plan.outputs.action == 'skip'" in jobs
    assert "Reject unknown plan action" in jobs
    assert "DEST_TAGS: ${{ steps.meta.outputs.tags }}" in jobs
    assert "for tag in ${DEST_TAGS}" in jobs
    assert "if: steps.plan.outputs.action == 'rebuild'" in jobs
    assert "docker/setup-qemu-action@v3" in jobs
    assert "docker/build-push-action@v6" in jobs
