"""Build and lock the official Attempt base image.

Usage:
  python -m ageval.plugins.contrib.docker.attempt.build \\
      --platform linux/arm64

The recipe lives next to this module (wheel or checkout). ``ageval run``
imports ``build_official_image``; it does not look under the process cwd.

``--python-version`` selects the base CPython minor (default 3.12). The
Dockerfile resolves ``FROM python:${PYTHON_VERSION}-slim-bookworm``; a
non-default version also switches the default ``--tag`` to the versioned
``ageval-attempt:py<version>`` so bases coexist instead of overwriting.

Optional process / host-env knobs (empty = official Debian / PyPI):

  AGEVAL_APT_MIRROR   e.g. http://mirrors.aliyun.com/debian
  AGEVAL_PIP_INDEX    e.g. https://pypi.tuna.tsinghua.edu.cn/simple
                      (plugin bake layers read the same knob)

``ageval run`` already loads Dataset / cwd / repo ``.env`` before prepare.
A bare invocation here loads cwd / parent ``.env`` files when importable.
Do not put these knobs in ``~/.zshrc`` — process env would mask Dataset ``.env``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as py_platform
import re
import subprocess
import sys
from pathlib import Path

from ageval.plugins.contrib.docker.attempt import (
    ATTEMPT_DIR,
    DEFAULT_PYTHON_VERSION,
    official_lock_path,
)

BUILD_INPUT_NAMES = ("Dockerfile", "install-executors.sh", "acp-entries.lock.json")
_PYTHON_VERSION_RE = re.compile(r"^\d+\.\d+$")
_GENERATOR = "ageval.plugins.contrib.docker.attempt.build"


class OfficialBuildError(Exception):
    """The official base image could not be built or probed."""


def valid_python_version(text: str) -> bool:
    """A CPython minor like ``3.13``; ``latest`` / ``3`` / empty are not."""
    return _PYTHON_VERSION_RE.fullmatch(text) is not None


def versioned_tag(version: str) -> str:
    return f"ageval-attempt:py{version}"


def default_tag(python_version: str) -> str:
    """3.12 is ``ageval-attempt:base``; other versions get their own tag."""
    if python_version == DEFAULT_PYTHON_VERSION:
        return "ageval-attempt:base"
    return versioned_tag(python_version)


def host_platform() -> str:
    machine = py_platform.machine().lower()
    return "linux/arm64" if machine in {"arm64", "aarch64"} else "linux/amd64"


def official_attempt_dir() -> Path:
    return ATTEMPT_DIR


def prepare_official_build_env() -> tuple[str, str]:
    return (os.environ.get("AGEVAL_APT_MIRROR") or "").strip(), (
        os.environ.get("AGEVAL_PIP_INDEX") or ""
    ).strip()


def official_build_input_digest(
    attempt_dir: Path, *, apt_mirror: str, pip_index: str, python_version: str
) -> str:
    hasher = hashlib.sha256()
    hasher.update(f"{apt_mirror}\n{pip_index}\n{python_version}\n".encode())
    for name in BUILD_INPUT_NAMES:
        path = attempt_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"missing build input: {path}")
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def official_buildx_command(
    *,
    dockerfile: Path,
    tag: str,
    platform: str,
    context: Path,
    apt_mirror: str,
    pip_index: str,
    python_version: str,
) -> list[str]:
    cmd = ["docker", "build", "--platform", platform, "-f", str(dockerfile), "-t", tag]
    if apt_mirror:
        cmd.extend(["--build-arg", f"AGEVAL_APT_MIRROR={apt_mirror}"])
    if pip_index:
        cmd.extend(["--build-arg", f"AGEVAL_PIP_INDEX={pip_index}"])
    cmd.extend(["--build-arg", f"PYTHON_VERSION={python_version}"])
    cmd.append(str(context))
    return cmd


def _load_host_env() -> None:
    try:
        from ageval.application.host_env import load_host_env_files
    except ImportError:
        return
    load_host_env_files(package_root=Path.cwd())


def build_official_image(
    *,
    tag: str,
    python_version: str,
    platform: str,
    output_lock: Path,
    attempt_dir: Path | None = None,
) -> str:
    """Build the official base and write a lock. Return the image digest."""
    if not valid_python_version(python_version):
        raise OfficialBuildError(
            f"invalid python_version {python_version!r}: expected a CPython minor like 3.13"
        )
    recipe = attempt_dir if attempt_dir is not None else ATTEMPT_DIR
    dockerfile = recipe / "Dockerfile"
    if not dockerfile.is_file():
        raise OfficialBuildError(f"missing Dockerfile: {dockerfile}")

    apt_mirror, pip_index = prepare_official_build_env()
    try:
        build_input = official_build_input_digest(
            recipe,
            apt_mirror=apt_mirror,
            pip_index=pip_index,
            python_version=python_version,
        )
    except FileNotFoundError as exc:
        raise OfficialBuildError(str(exc)) from exc

    pin_lock = recipe / "acp-entries.lock.json"
    pin_doc = json.loads(pin_lock.read_text(encoding="utf-8"))

    cmd = official_buildx_command(
        dockerfile=dockerfile,
        tag=tag,
        platform=platform,
        context=recipe,
        apt_mirror=apt_mirror,
        pip_index=pip_index,
        python_version=python_version,
    )
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise OfficialBuildError((proc.stderr or proc.stdout or "").strip() or tag)

    inspect = subprocess.run(
        ["docker", "image", "inspect", tag, "--format", "{{json .Id}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if inspect.returncode != 0:
        raise OfficialBuildError((inspect.stderr or "").strip() or tag)
    image_id = json.loads(inspect.stdout.strip())
    dig = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            tag,
            "--format",
            "{{if .RepoDigests}}{{index .RepoDigests 0}}{{else}}{{.Id}}{{end}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    digest = (dig.stdout or image_id).strip()

    probe = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "10001:10001",
            tag,
            "bash",
            "-c",
            "command -v codex && command -v codex-acp && "
            "command -v pi && command -v pi-acp && "
            "command -v opencode && "
            "(command -v claude || command -v claude-code) && command -v claude-agent-acp && "
            "command -v grok",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "").strip()
        raise OfficialBuildError(
            f"post-build actor UID PATH probe failed{': ' + detail if detail else ''}"
        )

    lock = {
        "kind": "docker-attempt",
        "platform": platform,
        "python_version": python_version,
        "image_tag": tag,
        "image_id": image_id,
        "image_digest": digest,
        "build_input_digest": f"sha256:{build_input}",
        "build_input_files": list(BUILD_INPUT_NAMES),
        "acp_entries_lock": pin_doc,
        "generator": _GENERATOR,
        "runtime_abi": f"python{python_version}",
        "actor_uid_path_probe": "ok",
    }
    output_lock.parent.mkdir(parents=True, exist_ok=True)
    output_lock.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--platform",
        default=None,
        help="docker platform (default: this host)",
    )
    parser.add_argument(
        "--python-version",
        default=DEFAULT_PYTHON_VERSION,
        help="base CPython minor, e.g. 3.13 (default 3.12)",
    )
    parser.add_argument(
        "--output-lock",
        type=Path,
        default=None,
    )
    parser.add_argument("--tag", default=None)
    args = parser.parse_args(argv)

    python_version = args.python_version.strip()
    if not valid_python_version(python_version):
        print(
            f"invalid --python-version {args.python_version!r}: expected a CPython minor like 3.13",
            file=sys.stderr,
        )
        return 2

    tag = args.tag if args.tag is not None else default_tag(python_version)
    platform = (args.platform or "").strip() or host_platform()
    output_lock = (
        args.output_lock if args.output_lock is not None else official_lock_path(python_version)
    )

    _load_host_env()
    try:
        digest = build_official_image(
            tag=tag,
            python_version=python_version,
            platform=platform,
            output_lock=output_lock,
        )
    except OfficialBuildError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "image_tag": tag,
                "image_digest": digest,
                "platform": platform,
                "python_version": python_version,
                "output_lock": str(output_lock),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
