"""Images the docker box runs: the official base, then the task's own recipe.

The cache key is the recipe plus what it copies, never the task id or the lock
digest — two tasks with the same recipe share one image, and editing the recipe
invalidates it.

Plugin bake layers honor parent ``AGEVAL_PIP_INDEX`` (same knob as the
official Attempt build). Unset omits the build-arg and leaves the content
key unchanged. A non-empty value is ``PIP_INDEX_URL`` on the plugin-layer
build only — task recipes and the official base path are untouched.

``python_version`` selects the official base's CPython. The default keeps
``ageval-attempt:base``; another minor builds ``ageval-attempt:py<version>``.
A recipe ``FROM ageval-attempt:base`` resolves onto that tag, so two bases
coexist locally.

When the local tag is missing, ``ensure_base_image`` pulls
``ghcr.io/zju-real/ageval-attempt:<cli-version>`` (same version as the
installed ``ageval-cli`` wheel) and retags it locally. A miss — private
package, no matching tag, wrong arch — falls through to the packaged
Dockerfile once. Invoke still does not ``npm i``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

from ageval.environments.protocol import EnvironmentFailure
from ageval.plugins.contrib.docker.attempt import official_lock_path
from ageval.plugins.contrib.docker.attempt.build import (
    OfficialBuildError,
    build_official_image,
    host_platform,
)

BASE_TAG = "ageval-attempt:base"
GHCR_ATTEMPT_IMAGE = "ghcr.io/zju-real/ageval-attempt"
PACKAGE_TAG_PREFIX = "ageval-pkg"
DEFAULT_PYTHON_VERSION = "3.12"

_BASE_FROM_RE = re.compile(
    r"^FROM(?P<flags>(?:\s+--[^\s]+)*)\s+ageval-attempt:base\b",
    re.IGNORECASE | re.MULTILINE,
)
_COPY_HEAD = re.compile(r"^(COPY|ADD)\s+", re.IGNORECASE)
_SKIP_COPY_NAMES = frozenset({".ageval", ".git", "__pycache__", "node_modules"})
_DIGEST_FORMAT = "{{if .RepoDigests}}{{index .RepoDigests 0}}{{else}}{{.Id}}{{end}}"


def docker(*args: str, timeout: float = 600.0) -> subprocess.CompletedProcess[str]:
    """Run one docker CLI command with the parent's daemon environment."""
    return subprocess.run(  # noqa: S603 — argv is built here, never a shell string
        ["docker", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def daemon_available() -> bool:
    return docker("version", "--format", "{{.Server.Version}}", timeout=30.0).returncode == 0


def image_digest(tag: str) -> str | None:
    """Digest of an existing local tag, or None when it is not there."""
    found = docker("image", "inspect", tag, "--format", _DIGEST_FORMAT, timeout=60.0)
    if found.returncode != 0:
        return None
    return (found.stdout or "").strip() or None


def base_tag_for(python_version: str | None) -> str:
    """The official base tag this job's CPython resolves to."""
    if not python_version or python_version == DEFAULT_PYTHON_VERSION:
        return BASE_TAG
    return f"ageval-attempt:py{python_version}"


def base_lock_path(python_version: str | None) -> Path:
    """Per-version build lock so two bases do not overwrite each other's record."""
    return official_lock_path(python_version)


def cli_package_version() -> str:
    """Installed ``ageval-cli`` version; empty when it cannot be resolved."""
    try:
        from importlib.metadata import version as pkg_version

        text = pkg_version("ageval-cli").strip()
    except Exception:  # noqa: BLE001 — offline / editable edge cases
        text = ""
    if not text or text.endswith("+unknown"):
        return ""
    return text


def official_remote_ref(python_version: str | None, *, version: str | None = None) -> str | None:
    """GHCR tag matching this CLI version, or None when we should not pull."""
    ver = (version if version is not None else cli_package_version()).strip()
    if not ver:
        return None
    if not python_version or python_version == DEFAULT_PYTHON_VERSION:
        return f"{GHCR_ATTEMPT_IMAGE}:{ver}"
    return f"{GHCR_ATTEMPT_IMAGE}:{ver}-py{python_version}"


def _pull_official_base(tag: str, *, python_version: str | None, platform: str) -> str | None:
    remote = official_remote_ref(python_version)
    if remote is None:
        return None
    pulled = docker("pull", "--platform", platform, remote)
    if pulled.returncode != 0:
        return None
    tagged = docker("tag", remote, tag)
    if tagged.returncode != 0:
        return None
    return image_digest(tag)


def ensure_base_image(*, python_version: str | None = None, platform: str | None = None) -> str:
    """Digest of the official base image, building it when absent.

    Local tag first, then GHCR ``ageval-attempt:<cli-version>``, then the
    packaged ``attempt/`` Dockerfile. The base bakes the ACP entries, so a
    run must never fall back to installing an agent at invoke time. A base
    whose upstream ``python:`` tag cannot be pulled fails the build once —
    there is no fallback to the default version.
    """
    tag = base_tag_for(python_version)
    digest = image_digest(tag)
    if digest is not None:
        return digest
    py = python_version or DEFAULT_PYTHON_VERSION
    plat = platform or host_platform()
    pulled = _pull_official_base(tag, python_version=python_version, platform=plat)
    if pulled:
        return pulled
    try:
        digest = build_official_image(
            tag=tag,
            python_version=py,
            platform=plat,
            output_lock=official_lock_path(python_version),
        )
    except OfficialBuildError as exc:
        raise EnvironmentFailure(
            "environment_image_unresolved",
            f"could not build the official base image {tag}: {exc}",
        ) from exc
    if not digest:
        raise EnvironmentFailure(
            "environment_image_unresolved",
            f"could not build the official base image {tag}",
        )
    return digest


def resolve_image(
    *,
    task_root: Path,
    dockerfile_rel: str | None,
    declared_image: str | None,
    platform: str,
    force_build: bool,
    plugin_layers: Sequence[tuple[str, str, str, str]] = (),
    python_version: str | None = None,
) -> tuple[str, str]:
    """Return ``(tag, digest)`` for this Attempt's image.

    A declared ``docker_image`` is used as-is. A task recipe is built on top of
    the official base, and the bound plugins' declared layers are baked on top
    of that. With neither, the base itself is the box.

    Each plugin layer is ``(plugin_id, dockerfile_path, package_root, body)``.
    """
    if declared_image:
        digest = image_digest(declared_image)
        if digest is None:
            pulled = docker("pull", declared_image)
            digest = image_digest(declared_image)
            if digest is None:
                raise EnvironmentFailure(
                    "environment_image_unresolved",
                    f"cannot resolve image {declared_image!r}: "
                    f"{(pulled.stderr or '').strip()[-300:]}",
                )
        return declared_image, digest

    base_digest = ensure_base_image(python_version=python_version, platform=platform)
    base_tag = base_tag_for(python_version)
    if dockerfile_rel is None and not plugin_layers:
        return base_tag, base_digest
    return build_task_image(
        task_root=task_root,
        dockerfile_rel=dockerfile_rel,
        platform=platform,
        base_digest=base_digest,
        base_tag=base_tag,
        force_build=force_build,
        plugin_layers=plugin_layers,
    )


def plugin_bake_pip_index() -> str:
    """Parent ``AGEVAL_PIP_INDEX`` for plugin bake layers. Empty = pip default."""
    return (os.environ.get("AGEVAL_PIP_INDEX") or "").strip()


def plugin_layer_build_args(base_image: str) -> tuple[str, ...]:
    """Build-args for one plugin ``Dockerfile.bake``. Unset index omits ``PIP_INDEX_URL``."""
    args = [f"BASE_IMAGE={base_image}"]
    pip_index = plugin_bake_pip_index()
    if pip_index:
        args.append(f"PIP_INDEX_URL={pip_index}")
    return tuple(args)


def build_task_image(
    *,
    task_root: Path,
    dockerfile_rel: str | None,
    platform: str,
    base_digest: str,
    base_tag: str = BASE_TAG,
    force_build: bool,
    plugin_layers: Sequence[tuple[str, str, str, str]] = (),
) -> tuple[str, str]:
    """Build the task recipe, then each plugin bake with its own context.

    The recipe's ``FROM ageval-attempt:base`` resolves onto ``base_tag`` so a
    non-default CPython base is the one under the task image.
    """
    recipe = _recipe_text(task_root, dockerfile_rel, base_tag)
    layer_key = "\n".join(f"{plugin_id}\n{body}" for plugin_id, _, _, body in plugin_layers)
    pip_index = plugin_bake_pip_index()
    if plugin_layers and pip_index:
        layer_key = f"{layer_key}\npip_index={pip_index}"
    content = content_digest(
        recipe=recipe + "\n" + layer_key,
        context_root=task_root,
        platform=platform,
        base_digest=base_digest,
        base_tag=base_tag,
    )
    tag = f"{PACKAGE_TAG_PREFIX}:{content[:12]}"
    if not force_build:
        existing = image_digest(tag)
        if existing is not None:
            return tag, existing

    current, _ = _build_named(
        recipe=recipe,
        context_root=task_root,
        tag=f"{PACKAGE_TAG_PREFIX}:{content[:12]}-base",
        platform=platform,
        build_args=(),
    )
    for plugin_id, _dockerfile, package_root, body in plugin_layers:
        current, _ = _build_named(
            recipe=body,
            context_root=Path(package_root),
            tag=f"{PACKAGE_TAG_PREFIX}:{content[:12]}-{plugin_id}",
            platform=platform,
            build_args=plugin_layer_build_args(current),
        )
    tagged = docker("tag", current, tag)
    if tagged.returncode != 0:
        raise EnvironmentFailure(
            "environment_image_unresolved",
            f"could not tag plugin image as {tag}: {(tagged.stderr or '')[-300:]}",
        )
    digest = image_digest(tag)
    if digest is None:
        raise EnvironmentFailure(
            "environment_image_unresolved",
            f"task image build failed for {tag}",
        )
    return tag, digest


def _build_named(
    *,
    recipe: str | None,
    context_root: Path,
    tag: str,
    platform: str,
    build_args: Sequence[str],
    dockerfile: Path | None = None,
) -> tuple[str, str]:
    generated: Path | None = None
    file_arg = dockerfile
    if recipe is not None:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".Dockerfile", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(recipe)
            generated = Path(handle.name)
        file_arg = generated
    assert file_arg is not None
    args = [
        "buildx",
        "build",
        "--platform",
        platform,
        "-f",
        str(file_arg),
        "-t",
        tag,
        "--load",
    ]
    for item in build_args:
        args.extend(["--build-arg", item])
    args.append(str(context_root))
    try:
        built = docker(*args, timeout=3600.0)
    finally:
        if generated is not None:
            generated.unlink(missing_ok=True)
    digest = image_digest(tag)
    if built.returncode != 0 or digest is None:
        raise EnvironmentFailure(
            "environment_image_unresolved",
            f"task image build failed: {(built.stderr or built.stdout or '')[-2000:]}",
        )
    return tag, digest


def _recipe_text(task_root: Path, dockerfile_rel: str | None, base_tag: str = BASE_TAG) -> str:
    """The task's recipe (base FROM resolved), or a bare FROM for plugins only."""
    if dockerfile_rel is None:
        return f"FROM {base_tag}\n"
    dockerfile = (task_root / dockerfile_rel).resolve()
    try:
        dockerfile.relative_to(task_root.resolve())
    except ValueError as exc:
        raise EnvironmentFailure(
            "environment_image_unresolved",
            f"recipe outside the task directory: {dockerfile_rel}",
        ) from exc
    if not dockerfile.is_file():
        raise EnvironmentFailure(
            "environment_image_unresolved",
            f"missing task recipe: {dockerfile_rel}",
        )
    recipe = dockerfile.read_text(encoding="utf-8")
    return _BASE_FROM_RE.sub(lambda m: f"FROM{m.group('flags')} {base_tag}", recipe)


def content_digest(
    *,
    recipe: str,
    context_root: Path,
    platform: str,
    base_digest: str,
    base_tag: str = BASE_TAG,
) -> str:
    """Recipe + base identity + copied bytes + platform.

    A non-default ``base_tag`` also enters the key, so 3.12 and 3.13 bases
    never share a task image even when the recipe text alone would collide.
    """
    hasher = hashlib.sha256()
    fields: list[tuple[bytes, str]] = [
        (b"dockerfile", recipe),
        (b"base", base_digest),
        (b"platform", platform),
    ]
    if base_tag != BASE_TAG:
        fields.append((b"python", base_tag))
    for label, payload in fields:
        hasher.update(label + b"\0" + payload.encode("utf-8") + b"\0")
    _hash_copy_sources(context_root, copy_sources(recipe), hasher)
    return hasher.hexdigest()


def logical_lines(text: str) -> list[str]:
    """Dockerfile lines with continuations joined and comments dropped."""
    lines: list[str] = []
    buffer: list[str] = []
    for raw in text.splitlines():
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            buffer.append(stripped[:-1].rstrip())
            continue
        buffer.append(stripped)
        joined = " ".join(part.strip() for part in buffer if part.strip())
        buffer = []
        if joined and not joined.startswith("#"):
            lines.append(joined)
    joined = " ".join(part.strip() for part in buffer if part.strip())
    if joined and not joined.startswith("#"):
        lines.append(joined)
    return lines


def copy_sources(text: str) -> list[str]:
    """COPY/ADD sources in the build context (multi-stage copies excluded)."""
    sources: list[str] = []
    for line in logical_lines(text):
        if not _COPY_HEAD.match(line):
            continue
        rest = _COPY_HEAD.sub("", line).strip()
        if re.search(r"--from=", rest, flags=re.IGNORECASE):
            continue
        if rest.startswith("["):
            try:
                parsed = json.loads(rest)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list) and len(parsed) >= 2:
                sources.extend(str(item) for item in parsed[:-1])
            continue
        try:
            tokens = [t for t in shlex.split(rest) if not t.startswith("-")]
        except ValueError:
            continue
        if len(tokens) >= 2:
            sources.extend(tokens[:-1])
    return sources


def _hash_copy_sources(
    context_root: Path,
    sources: Iterable[str],
    hasher: hashlib._Hash,
) -> None:
    root = context_root.resolve()
    seen: set[str] = set()
    for source in sources:
        rel = source.lstrip("./")
        if not rel or rel.startswith("/"):
            continue
        matches = (
            sorted(p for p in root.glob(rel) if p.exists())
            if any(ch in rel for ch in "*?[")
            else [root / rel]
        )
        for match in matches:
            for path in _files_under(match, root):
                key = str(path.relative_to(root)).replace("\\", "/")
                if key in seen:
                    continue
                seen.add(key)
                hasher.update(key.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")


def _files_under(path: Path, root: Path) -> Sequence[Path]:
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (ValueError, OSError):
        return ()
    if resolved.is_file():
        return () if _skipped(resolved, root) else (resolved,)
    if not resolved.is_dir():
        return ()
    return [p for p in sorted(resolved.rglob("*")) if p.is_file() and not _skipped(p, root)]


def _skipped(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    if any(part in _SKIP_COPY_NAMES for part in rel.parts):
        return True
    return path.suffix == ".pyc" or path.name == ".DS_Store"
