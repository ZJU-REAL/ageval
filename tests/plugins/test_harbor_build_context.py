"""Harbor docker build context stays inside the task and defaults to the task root."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.environments.protocol import EnvironmentFailure
from ageval.plugins.contrib.docker.images import _build_context


def test_omitted_context_is_the_task_root(tmp_path: Path) -> None:
    assert _build_context(tmp_path, None) == tmp_path
    assert _build_context(tmp_path, "") == tmp_path


def test_environment_directory_is_the_context(tmp_path: Path) -> None:
    env = tmp_path / "environment"
    env.mkdir()
    assert _build_context(tmp_path, "environment") == env.resolve()


def test_missing_or_escaping_context_fails(tmp_path: Path) -> None:
    with pytest.raises(EnvironmentFailure) as missing:
        _build_context(tmp_path, "environment")
    assert missing.value.kind == "harbor_build_context"
    with pytest.raises(EnvironmentFailure) as escaped:
        _build_context(tmp_path, "../outside")
    assert escaped.value.kind == "harbor_build_context"
