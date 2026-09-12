#!/usr/bin/env python3
"""Plan the official Attempt GHCR job: skip, retag, or rebuild.

Every published CLI version still gets ``ghcr.io/zju-real/ageval-attempt:<ver>``.
When bake inputs match the previous published GHCR image, copy that multi-arch
manifest list with ``docker buildx imagetools create`` instead of a QEMU rebuild.

Bake inputs (not the whole repo, not Dockerfile alone):

- ``src/ageval/plugins/contrib/docker/attempt/Dockerfile``
- ``src/ageval/plugins/contrib/docker/attempt/install-executors.sh``
- ``src/ageval/plugins/contrib/docker/attempt/acp-entries.lock.json``
- ``src/ageval/plugins/contrib/docker/attempt/sitecustomize.py``
- the job's ``PYTHON_VERSION`` build-arg

This set is the GHCR skip key. It is not ``BUILD_INPUT_NAMES`` in
``attempt/build.py`` (local ``ageval run`` digest; parent-only helpers stay out
of both lists). ``sitecustomize.py`` is COPY'd into the image, so it belongs here.

Inspect failures do not skip. A missing previous tag or an inspect that is not a
clean not-found rebuilds. Same-tag already on GHCR is a no-op unless
``--force-rebuild``.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ATTEMPT_IMAGE = "ghcr.io/zju-real/ageval-attempt"
ATTEMPT_DIR = "src/ageval/plugins/contrib/docker/attempt"
WORKFLOW_PATH = ".github/workflows/release-images.yml"
DEFAULT_PYTHON_VERSION = "3.12"
BAKE_RELPATHS = (
    f"{ATTEMPT_DIR}/Dockerfile",
    f"{ATTEMPT_DIR}/install-executors.sh",
    f"{ATTEMPT_DIR}/acp-entries.lock.json",
    f"{ATTEMPT_DIR}/sitecustomize.py",
)
_RELEASE_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_WORKFLOW_PYTHON_RE = re.compile(
    r"(?:ATTEMPT_PYTHON_VERSION|PYTHON_VERSION)\s*[:=]\s*[\"']?(\d+\.\d+)"
)
_NOT_FOUND_MARKERS = (
    "not found",
    "name unknown",
    "manifest unknown",
    "no such",
    "404",
)
InspectFn = Callable[[str], str]


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    source_version: str = ""
    source_ref: str = ""

    def as_github_output(self) -> str:
        return (
            f"action={self.action}\n"
            f"reason={self.reason}\n"
            f"source_version={self.source_version}\n"
            f"source_ref={self.source_ref}\n"
        )


def parse_release_tag(tag: str) -> str | None:
    """``v0.8.0`` → ``0.8.0``. Prerelease / extra suffix → None."""
    match = _RELEASE_TAG_RE.fullmatch(tag.strip())
    if match is None:
        return None
    return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"


def normalize_version(value: str) -> str:
    text = value.strip()
    parsed = parse_release_tag(text)
    if parsed is not None:
        return parsed
    if _VERSION_RE.fullmatch(text) is None:
        raise ValueError(f"version must be vMAJOR.MINOR.PATCH, got {value!r}")
    return text


def version_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def workflow_python_version(text: str) -> str:
    matches = _WORKFLOW_PYTHON_RE.findall(text)
    return matches[-1] if matches else ""


def bake_digest(files: dict[str, bytes | None], python_version: str) -> str:
    hasher = hashlib.sha256()
    hasher.update(f"PYTHON_VERSION={python_version}\n".encode())
    for relpath in BAKE_RELPATHS:
        hasher.update(relpath.encode())
        hasher.update(b"\0")
        data = files.get(relpath)
        if data is None:
            hasher.update(b"MISSING\n")
        else:
            hasher.update(data)
        hasher.update(b"\n")
    return hasher.hexdigest()


def head_bake_files(repo: Path) -> dict[str, bytes | None]:
    files: dict[str, bytes | None] = {}
    missing: list[str] = []
    for relpath in BAKE_RELPATHS:
        path = repo / relpath
        if not path.is_file():
            missing.append(relpath)
            continue
        files[relpath] = path.read_bytes()
    if missing:
        raise FileNotFoundError("missing attempt bake inputs: " + ", ".join(missing))
    return files


def classify_inspect(returncode: int, stderr: str) -> str:
    if returncode == 0:
        return "exists"
    text = stderr.lower()
    if any(marker in text for marker in _NOT_FOUND_MARKERS):
        return "missing"
    return "error"


def older_release_versions(versions: Sequence[str], current: str) -> list[str]:
    current_key = version_key(current)
    older = [item for item in versions if version_key(item) < current_key]
    older.sort(key=version_key, reverse=True)
    return older


def git_release_versions(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "tag", "-l", "v*"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    versions: list[str] = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        parsed = parse_release_tag(line.strip())
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        versions.append(parsed)
    versions.sort(key=version_key, reverse=True)
    return versions


def git_show(repo: Path, ref: str, relpath: str) -> bytes | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:{relpath}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def bake_digest_at_tag(repo: Path, version: str) -> str:
    ref = f"v{version}"
    files = {relpath: git_show(repo, ref, relpath) for relpath in BAKE_RELPATHS}
    workflow = git_show(repo, ref, WORKFLOW_PATH)
    python_version = (
        workflow_python_version(workflow.decode("utf-8", "replace")) if workflow is not None else ""
    )
    return bake_digest(files, python_version)


def inspect_ghcr(image: str, version: str) -> str:
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", f"{image}:{version}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return classify_inspect(result.returncode, f"{result.stdout}\n{result.stderr}")


def decide(
    *,
    version: str,
    force_rebuild: bool,
    head_digest: str,
    previous_versions: Sequence[str],
    inspect: InspectFn,
    digest_for: Callable[[str], str],
    image: str = ATTEMPT_IMAGE,
) -> Decision:
    current = normalize_version(version)
    if force_rebuild:
        return Decision(action="rebuild", reason="force_rebuild")
    status = inspect(current)
    if status == "exists":
        return Decision(action="skip", reason="version_tag_exists")
    if status == "error":
        return Decision(action="rebuild", reason="inspect_failed")
    for previous in older_release_versions(previous_versions, current):
        previous_status = inspect(previous)
        if previous_status == "error":
            return Decision(action="rebuild", reason="inspect_failed")
        if previous_status == "missing":
            continue
        if digest_for(previous) == head_digest:
            return Decision(
                action="retag",
                reason="inputs_unchanged",
                source_version=previous,
                source_ref=f"{image}:{previous}",
            )
        return Decision(action="rebuild", reason="inputs_changed")
    return Decision(action="rebuild", reason="no_previous_image")


def plan_from_git(
    repo: Path,
    *,
    version: str,
    python_version: str,
    force_rebuild: bool,
    inspect: InspectFn,
    image: str = ATTEMPT_IMAGE,
) -> Decision:
    head = bake_digest(head_bake_files(repo), python_version)
    return decide(
        version=version,
        force_rebuild=force_rebuild,
        head_digest=head,
        previous_versions=git_release_versions(repo),
        inspect=inspect,
        digest_for=lambda previous: bake_digest_at_tag(repo, previous),
        image=image,
    )


def write_github_output(path: Path, decision: Decision) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    path.write_text(existing + decision.as_github_output(), encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="CLI version, with or without a v prefix")
    parser.add_argument(
        "--python-version",
        default=DEFAULT_PYTHON_VERSION,
        help="Attempt job PYTHON_VERSION build-arg",
    )
    parser.add_argument(
        "--force-rebuild",
        default="false",
        help="true/false; rebuild even when the version tag already exists",
    )
    parser.add_argument("--image", default=ATTEMPT_IMAGE)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--github-output",
        type=Path,
        default=None,
        help="Append GITHUB_OUTPUT keys; defaults to $GITHUB_OUTPUT when set",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        version = normalize_version(args.version)
    except ValueError as exc:
        print(f"attempt_image_release: {exc}", file=sys.stderr)
        return 2
    repo = args.repo.resolve()
    try:
        decision = plan_from_git(
            repo,
            version=version,
            python_version=args.python_version,
            force_rebuild=parse_bool(str(args.force_rebuild)),
            inspect=lambda ver: inspect_ghcr(args.image, ver),
            image=args.image,
        )
    except FileNotFoundError as exc:
        print(f"attempt_image_release: {exc}", file=sys.stderr)
        return 2
    print(
        f"action={decision.action} reason={decision.reason} source_ref={decision.source_ref or '-'}"
    )
    output = args.github_output
    if output is None:
        env_out = os.environ.get("GITHUB_OUTPUT")
        output = Path(env_out) if env_out else None
    if output is not None:
        write_github_output(output, decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
