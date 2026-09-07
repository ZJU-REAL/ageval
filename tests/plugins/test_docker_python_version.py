"""docker environment_options.python_version — base selection and FROM resolve."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ageval.environments.protocol import BoxSpec, EnvironmentFailure
from ageval.plugins.contrib.docker import images
from ageval.plugins.contrib.docker.host import DockerHost, _box_python_version


def test_python_version_omitted_is_none() -> None:
    assert _box_python_version(None) is None


@pytest.mark.parametrize("raw", ["3.9", "3.10", "3.13"])
def test_python_version_accepts_minor(raw: str) -> None:
    assert _box_python_version(raw) == raw


@pytest.mark.parametrize("raw", ["", "latest", "3", "  ", "3.13.1", True, 3.13])
def test_python_version_rejects_other_shapes(raw: object) -> None:
    with pytest.raises(EnvironmentFailure, match="CPython minor"):
        _box_python_version(raw)


def test_host_constructor_rejects_bad_python_version(tmp_path: Path) -> None:
    spec = BoxSpec(attempt_root=tmp_path / "box", task_root=tmp_path, repo_root=tmp_path)
    with pytest.raises(EnvironmentFailure, match="CPython minor"):
        DockerHost(spec=spec, options={"python_version": "latest"})


def test_base_tag_default_and_versioned() -> None:
    assert images.base_tag_for(None) == "ageval-attempt:base"
    assert images.base_tag_for("3.12") == "ageval-attempt:base"
    assert images.base_tag_for("3.13") == "ageval-attempt:py3.13"


def test_base_lock_path_versions_non_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGEVAL_HOME", str(tmp_path))
    assert (
        images.base_lock_path(None) == tmp_path.resolve() / "runtime-images" / "attempt-base.json"
    )
    assert images.base_lock_path("3.13").name == "attempt-base-py3.13.json"


def test_recipe_from_resolves_onto_versioned_base(tmp_path: Path) -> None:
    recipe = tmp_path / "Dockerfile"
    recipe.write_text(
        "FROM ageval-attempt:base\nRUN pip install x\n# FROM ageval-attempt:base in a comment\n",
        encoding="utf-8",
    )
    assert images._recipe_text(tmp_path, "Dockerfile") == recipe.read_text(encoding="utf-8")
    resolved = images._recipe_text(tmp_path, "Dockerfile", "ageval-attempt:py3.13")
    assert resolved.startswith("FROM ageval-attempt:py3.13\n")
    assert "RUN pip install x\n" in resolved


def test_bare_recipe_uses_versioned_base() -> None:
    assert images._recipe_text(Path("."), None) == "FROM ageval-attempt:base\n"
    assert (
        images._recipe_text(Path("."), None, "ageval-attempt:py3.13")
        == "FROM ageval-attempt:py3.13\n"
    )


def test_recipe_from_with_build_flags_resolves_onto_versioned_base(tmp_path: Path) -> None:
    text = "FROM --platform=linux/arm64 ageval-attempt:base\nRUN pip install x\n"
    recipe = tmp_path / "Dockerfile"
    recipe.write_text(text, encoding="utf-8")
    assert images._recipe_text(tmp_path, "Dockerfile") == text
    resolved = images._recipe_text(tmp_path, "Dockerfile", "ageval-attempt:py3.13")
    assert resolved.startswith("FROM --platform=linux/arm64 ageval-attempt:py3.13\n")


def test_content_digest_separates_python_bases(tmp_path: Path) -> None:
    common = {
        "recipe": "FROM ageval-attempt:base\n",
        "context_root": tmp_path,
        "platform": "linux/arm64",
        "base_digest": "sha256:x",
    }
    default = images.content_digest(**common, base_tag=images.BASE_TAG)
    assert default == images.content_digest(**common)
    assert default != images.content_digest(**common, base_tag="ageval-attempt:py3.13")


class _FakeDaemon:
    """image inspect + buildx tag bookkeeping, like the pip-index tests."""

    def __init__(self) -> None:
        self.images: set[str] = set()
        self.builds: list[tuple[str, str]] = []  # (tag, dockerfile text)

    def __call__(self, *args: str, timeout: float = 600.0) -> subprocess.CompletedProcess[str]:
        del timeout
        if args[:2] == ("image", "inspect"):
            tag = args[2]
            if tag in self.images:
                return subprocess.CompletedProcess(
                    list(args), 0, stdout=f"sha256:{tag}\n", stderr=""
                )
            return subprocess.CompletedProcess(list(args), 1, stdout="", stderr="missing")
        if args[:2] == ("buildx", "build"):
            tag = args[args.index("-t") + 1]
            source = Path(args[args.index("-f") + 1])
            self.builds.append((tag, source.read_text(encoding="utf-8")))
            self.images.add(tag)
            return subprocess.CompletedProcess(list(args), 0, stdout="", stderr="")
        if args[0] == "pull":
            image = args[-1]
            if image in self.images:
                return subprocess.CompletedProcess(list(args), 0, stdout="", stderr="")
            return subprocess.CompletedProcess(list(args), 1, stdout="", stderr="missing")
        if args[0] == "tag":
            src, dest = args[1], args[2]
            if src in self.images:
                self.images.add(dest)
                return subprocess.CompletedProcess(list(args), 0, stdout="", stderr="")
            return subprocess.CompletedProcess(list(args), 1, stdout="", stderr="missing src")
        return subprocess.CompletedProcess(list(args), 1, stdout="", stderr=f"unexpected {args}")


def _fake_official_build(
    monkeypatch: pytest.MonkeyPatch, daemon: _FakeDaemon
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def build_official_image(
        *,
        tag: str,
        python_version: str,
        platform: str,
        output_lock: Path,
        attempt_dir: Path | None = None,
    ) -> str:
        del attempt_dir
        calls.append(
            {
                "tag": tag,
                "python_version": python_version,
                "platform": platform,
                "output_lock": output_lock,
            }
        )
        daemon.images.add(tag)
        return f"sha256:{tag}"

    monkeypatch.setattr(images, "build_official_image", build_official_image)
    return calls


def test_resolve_image_builds_versioned_base_and_resolves_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    daemon = _FakeDaemon()
    monkeypatch.setattr(images, "docker", daemon)
    build_calls = _fake_official_build(monkeypatch, daemon)
    (tmp_path / "Dockerfile").write_text("FROM ageval-attempt:base\n", encoding="utf-8")

    tag, _digest = images.resolve_image(
        task_root=tmp_path,
        dockerfile_rel="Dockerfile",
        declared_image=None,
        platform="linux/arm64",
        force_build=True,
        python_version="3.13",
    )

    assert tag.startswith("ageval-pkg:")
    assert build_calls == [
        {
            "tag": "ageval-attempt:py3.13",
            "python_version": "3.13",
            "platform": "linux/arm64",
            "output_lock": images.base_lock_path("3.13"),
        }
    ]
    assert len(daemon.builds) == 1
    assert daemon.builds[0][1].startswith("FROM ageval-attempt:py3.13")


def test_resolve_image_without_recipe_returns_versioned_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    daemon = _FakeDaemon()
    monkeypatch.setattr(images, "docker", daemon)
    _fake_official_build(monkeypatch, daemon)

    tag, _digest = images.resolve_image(
        task_root=tmp_path,
        dockerfile_rel=None,
        declared_image=None,
        platform="linux/arm64",
        force_build=False,
        python_version="3.13",
    )

    assert tag == "ageval-attempt:py3.13"


def test_resolve_image_default_keeps_base_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del tmp_path
    daemon = _FakeDaemon()
    monkeypatch.setattr(images, "docker", daemon)
    build_calls = _fake_official_build(monkeypatch, daemon)

    tag, _digest = images.resolve_image(
        task_root=Path("."),
        dockerfile_rel=None,
        declared_image=None,
        platform="linux/arm64",
        force_build=False,
    )

    assert tag == "ageval-attempt:base"
    assert build_calls[0]["tag"] == "ageval-attempt:base"
    assert build_calls[0]["python_version"] == "3.12"


def test_ensure_base_image_pulls_ghcr_before_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon = _FakeDaemon()
    monkeypatch.setattr(images, "docker", daemon)
    monkeypatch.setattr(images, "cli_package_version", lambda: "0.7.3")
    remote = "ghcr.io/zju-real/ageval-attempt:0.7.3"
    daemon.images.add(remote)
    builds = _fake_official_build(monkeypatch, daemon)

    digest = images.ensure_base_image(platform="linux/arm64")

    assert digest == f"sha256:{images.BASE_TAG}"
    assert images.BASE_TAG in daemon.images
    assert builds == []


def test_ensure_base_image_builds_when_ghcr_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon = _FakeDaemon()
    monkeypatch.setattr(images, "docker", daemon)
    monkeypatch.setattr(images, "cli_package_version", lambda: "0.7.3")
    builds = _fake_official_build(monkeypatch, daemon)

    digest = images.ensure_base_image(platform="linux/amd64")

    assert digest == f"sha256:{images.BASE_TAG}"
    assert builds[0]["tag"] == images.BASE_TAG


def test_official_remote_ref_versions() -> None:
    assert images.official_remote_ref(None, version="0.7.3") == (
        "ghcr.io/zju-real/ageval-attempt:0.7.3"
    )
    assert images.official_remote_ref("3.13", version="0.7.3") == (
        "ghcr.io/zju-real/ageval-attempt:0.7.3-py3.13"
    )
    assert images.official_remote_ref(None, version="") is None


def test_ensure_base_image_ignores_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    daemon = _FakeDaemon()
    monkeypatch.setattr(images, "docker", daemon)
    calls = _fake_official_build(monkeypatch, daemon)

    digest = images.ensure_base_image(python_version="3.13", platform="linux/amd64")

    assert digest == "sha256:ageval-attempt:py3.13"
    assert calls[0]["tag"] == "ageval-attempt:py3.13"
    assert calls[0]["platform"] == "linux/amd64"
    assert not (tmp_path / "docker").exists()


def test_missing_upstream_base_fails_once_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon = _FakeDaemon()
    monkeypatch.setattr(images, "docker", daemon)

    def fail_build(**kwargs: object) -> str:
        del kwargs
        raise images.OfficialBuildError("pull access denied")

    monkeypatch.setattr(images, "build_official_image", fail_build)

    with pytest.raises(EnvironmentFailure, match="ageval-attempt:py3.13"):
        images.ensure_base_image(python_version="3.13")
