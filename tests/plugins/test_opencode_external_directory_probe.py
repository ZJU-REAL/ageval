"""Pinned OpenCode must allow an external /tmp read inside a disposable image.

The unit matcher always runs. The container probe skips when Docker is
disabled, the daemon is down, or no local Attempt image has the packaged
OpenCode version. It does not install OpenCode and does not pass ``--auto``.
"""

from __future__ import annotations

import json
import os
import platform
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from ageval.plugins.contrib.acp.lock_overlay import (
    build_opencode_overlays,
    packaged_opencode_version,
)

# Captured from opencode 1.18.12 with no permission policy, reading /etc/hostname.
# The ask and the action share one line. A later "asking" line does not.
_NEGATIVE_ASK = (
    "message=evaluated permission=external_directory pattern=/etc/* "
    "action.permission=external_directory action.pattern=* action.action=ask"
)
_PROBE_TIMEOUT_SEC = 90


def external_directory_ask(log: str) -> str | None:
    """The log line where one evaluation both names external_directory and asks."""
    for line in log.splitlines():
        if "permission=external_directory" in line and "action.action=ask" in line:
            return line
    return None


def external_directory_allow(log: str) -> bool:
    for line in log.splitlines():
        if "permission=external_directory" in line and "action.action=allow" in line:
            return True
    return False


def test_external_directory_ask_matches_the_negative_control_line() -> None:
    assert external_directory_ask(_NEGATIVE_ASK) == _NEGATIVE_ASK
    allowed = _NEGATIVE_ASK.replace("action.action=ask", "action.action=allow")
    assert external_directory_ask(allowed) is None
    assert external_directory_allow(allowed)
    asking = (
        "message=asking id=per_20e6be1670011G2GU2IZZs72I9 "
        'permission=external_directory patterns="[\\"/etc/*\\"]"'
    )
    assert external_directory_ask(asking) is None
    assert external_directory_ask("permission=external_directory\naction.action=ask") is None


def _skip_docker_reason() -> str | None:
    flag = os.environ.get("AGEVAL_SKIP_DOCKER", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return "AGEVAL_SKIP_DOCKER=1"
    if shutil.which("docker") is None:
        return "docker is not on PATH"
    info = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=20)
    if info.returncode != 0:
        detail = (info.stderr or info.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else "docker info failed"
        return f"docker daemon is not available ({tail})"
    return None


def _candidate_images() -> list[str]:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        arch = "ageval-attempt:base-arm64"
    elif machine in {"x86_64", "amd64"}:
        arch = "ageval-attempt:base-amd64"
    else:
        arch = ""
    images = [arch] if arch else []
    if "ageval-attempt:base" not in images:
        images.append("ageval-attempt:base")
    return images


def _image_present(tag: str) -> bool:
    found = _run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
        timeout=20,
    )
    return found.returncode == 0 and bool(found.stdout.strip())


def _image_opencode_version(tag: str) -> str | None:
    proc = _run(
        ["docker", "run", "--rm", "--entrypoint", "opencode", tag, "--version"],
        timeout=40,
    )
    if proc.returncode != 0:
        return None
    text = proc.stdout.strip()
    return text or None


def _pinned_image(version: str) -> str | None:
    for tag in _candidate_images():
        if not _image_present(tag):
            continue
        if _image_opencode_version(tag) == version:
            return tag
    return None


def _run(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=stdout,
            stderr=stderr + "\n[timeout]",
        )


def _permission_only_config(path: Path) -> None:
    files = build_opencode_overlays(
        [{"model": {"id": "entry-default"}, "options": {"entry": "opencode"}}],
        environment="docker",
    )
    assert len(files) == 1
    payload = files[0].payload
    assert isinstance(payload, dict)
    assert "model" not in payload
    assert payload["permission"]["external_directory"] == "allow"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o644)


def test_pinned_opencode_allows_tmp_read() -> None:
    reason = _skip_docker_reason()
    if reason:
        pytest.skip(reason)
    version = packaged_opencode_version()
    if not version:
        pytest.skip("packaged opencode entry has no version")
    image = _pinned_image(version)
    if image is None:
        pytest.skip(f"no local Attempt image contains OpenCode {version}")

    token = "ageval-oc-" + secrets.token_hex(8)
    prompt = "Print the exact contents of /tmp/ageval-oc-probe.txt."
    assert token not in prompt
    # A file mount leaves /home unwritable, so OpenCode dies in mkdir of
    # /home/.local before it evaluates a tool. Host /tmp is what the image
    # can write through the Docker mount.
    home = Path(tempfile.mkdtemp(prefix="ageval-oc-home-"))
    work = Path(tempfile.mkdtemp(prefix="ageval-oc-work-"))
    probe_dir = Path(tempfile.mkdtemp(prefix="ageval-oc-probe-"))
    name = "ageval-oc-perm-" + secrets.token_hex(4)
    try:
        config_dir = home / ".config" / "opencode"
        config_dir.mkdir(parents=True)
        for directory in (home, home / ".config", config_dir, work, probe_dir):
            directory.chmod(0o777)
        config = config_dir / "opencode.json"
        probe = probe_dir / "probe.txt"
        _permission_only_config(config)
        probe.write_text(token + "\n", encoding="utf-8")
        probe.chmod(0o644)
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "-e",
            "HOME=/home",
            "-e",
            "OPENCODE_DISABLE_PROJECT_CONFIG=1",
            "-v",
            f"{home}:/home",
            "-v",
            f"{probe}:/tmp/ageval-oc-probe.txt:ro",
            "-v",
            f"{work}:/work",
            "-w",
            "/work",
            "--entrypoint",
            "opencode",
            image,
            "run",
            "--model",
            "opencode/big-pickle",
            "--format",
            "json",
            "--pure",
            "--print-logs",
            "--log-level",
            "INFO",
            prompt,
        ]
        proc = _run(command, timeout=_PROBE_TIMEOUT_SEC)
    finally:
        _run(["docker", "rm", "-f", name], timeout=20)
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(probe_dir, ignore_errors=True)
    log = f"{proc.stdout}\n{proc.stderr}"
    asked = external_directory_ask(log)
    if asked:
        pytest.fail(f"external_directory asked: {asked}")
    if token in log or external_directory_allow(log):
        return
    tail = log.strip()[-500:]
    started = "message=" in log or log.lstrip().startswith("{")
    if proc.returncode != 0 and started:
        pytest.skip(f"model or network failed before a tool evaluation: {tail}")
    pytest.fail(f"probe did not read the file (exit {proc.returncode}): {tail}")
