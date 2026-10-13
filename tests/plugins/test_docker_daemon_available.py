"""daemon_available() reports False instead of crashing when docker is absent."""

from __future__ import annotations

import subprocess

import pytest

from ageval.plugins.contrib.docker import images


def test_missing_docker_cli_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_docker(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", "docker")

    monkeypatch.setattr(images.subprocess, "run", no_docker)
    assert images.daemon_available() is False


def test_daemon_answer_decides(monkeypatch: pytest.MonkeyPatch) -> None:
    def answer(code: int):
        def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, code, stdout="", stderr="")

        return run

    monkeypatch.setattr(images.subprocess, "run", answer(0))
    assert images.daemon_available() is True
    monkeypatch.setattr(images.subprocess, "run", answer(1))
    assert images.daemon_available() is False
