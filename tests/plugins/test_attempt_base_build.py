"""Official Attempt base build — CPython selection, packaged recipe, versioned tags."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.plugins.contrib.docker.attempt import ATTEMPT_DIR, build


@pytest.mark.parametrize("version", ["3.9", "3.10", "3.12", "3.13"])
def test_valid_python_version_shape(version: str) -> None:
    assert build.valid_python_version(version)


@pytest.mark.parametrize("version", ["latest", "3", "", "3.13.1", "v3.13", "3.13 ", "x"])
def test_invalid_python_version_shape(version: str) -> None:
    assert not build.valid_python_version(version)


def test_default_tag_keeps_base_for_312_and_versions_others() -> None:
    assert build.default_tag("3.12") == "ageval-attempt:base"
    assert build.default_tag("3.13") == "ageval-attempt:py3.13"


def test_packaged_attempt_dir_ships_build_inputs() -> None:
    assert build.official_attempt_dir() == ATTEMPT_DIR
    for name in build.BUILD_INPUT_NAMES:
        assert (ATTEMPT_DIR / name).is_file(), name


def test_buildx_command_passes_python_version(tmp_path: Path) -> None:
    cmd = build.official_buildx_command(
        dockerfile=tmp_path / "Dockerfile",
        tag="ageval-attempt:py3.13",
        platform="linux/arm64",
        context=tmp_path,
        apt_mirror="",
        pip_index="",
        python_version="3.13",
    )
    assert cmd[cmd.index("--build-arg") + 1] == "PYTHON_VERSION=3.13"


def test_build_input_digest_tracks_python_version(tmp_path: Path) -> None:
    for name in build.BUILD_INPUT_NAMES:
        (tmp_path / name).write_text(f"{name}\n", encoding="utf-8")
    common = {"apt_mirror": "", "pip_index": ""}
    digest_312 = build.official_build_input_digest(tmp_path, python_version="3.12", **common)
    digest_313 = build.official_build_input_digest(tmp_path, python_version="3.13", **common)
    assert digest_312 != digest_313


@pytest.mark.parametrize("version", ["latest", "3", ""])
def test_main_rejects_invalid_python_version_before_docker(version: str) -> None:
    assert build.main(["--python-version", version]) == 2
