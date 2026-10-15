"""The attempt HOME an ACP entry runs against.

Engines read config and credentials from HOME, so the Attempt gets its own —
never the host's. This module owns both halves of that arrangement: the
directories created inside the box, and the env that points the entry at them.

BYOA entries authenticate with a file rather than a key, so the auth files an
entry declares are copied in from the host HOME when they exist. Only what the
entry declared, only into this Attempt's box, never into the lock or evidence.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ageval.environments.protocol import HOME_PATH, EnvironmentFailure
from ageval.plugins.contrib.acp.lock_overlay import OverlayFile
from ageval.plugins.contrib.acp.registry import AcpEntryDescriptor

# XDG defaults every entry inherits, on top of its declared ``home_dirs``.
_BASE_HOME_DIRS: tuple[str, ...] = (".config", ".cache", ".local/state", ".local/share")


def home_env(descriptor: AcpEntryDescriptor, home: str) -> dict[str, str]:
    """Point the entry's config, cache and state at the attempt HOME.

    *home* must already be process-visible (``host.visible_path``), because
    these values are read by the entry, not by the box.
    """
    env = {
        "HOME": home,
        "XDG_CONFIG_HOME": f"{home}/.config",
        "XDG_CACHE_HOME": f"{home}/.cache",
        "XDG_STATE_HOME": f"{home}/.local/state",
        "XDG_DATA_HOME": f"{home}/.local/share",
    }
    if ".codex" in descriptor.home_dirs:
        env["CODEX_HOME"] = f"{home}/.codex"
    return env


async def prepare_home(
    host: Any,
    descriptor: AcpEntryDescriptor,
    *,
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    """Create the entry's HOME layout in the box and copy declared auth files."""
    dirs = [*_BASE_HOME_DIRS, *descriptor.home_dirs]
    result = await host.exec(
        ["sh", "-c", " ".join(["mkdir", "-p", *(f"'{rel}'" for rel in dirs)])],
        cwd=HOME_PATH,
        timeout_sec=timeout_sec,
    )
    if result.exit_code != 0:
        raise EnvironmentFailure(
            "acp_home_prepare_failed",
            f"could not create the attempt HOME layout: {result.stderr.strip()[-300:]}",
        )
    return {"dirs": dirs, "auth_files": await _copy_keyless_auth(host, descriptor)}


async def write_lock_overlays(
    host: Any,
    files: list[OverlayFile],
    *,
    timeout_sec: float | None = None,
) -> list[str]:
    """Upload generated overlay files into Attempt HOME. Dest paths are relative."""
    written: list[str] = []
    for item in files:
        dest = item.dest.strip().lstrip("/")
        if not dest or ".." in Path(dest).parts:
            raise EnvironmentFailure(
                "acp_lock_overlay_invalid",
                f"refusing overlay dest {item.dest!r}",
            )
        parent = str(Path(dest).parent)
        if parent not in (".", ""):
            mkdir = await host.exec(
                ["mkdir", "-p", parent],
                cwd=HOME_PATH,
                timeout_sec=timeout_sec,
            )
            if mkdir.exit_code != 0:
                raise EnvironmentFailure(
                    "acp_home_prepare_failed",
                    f"could not create overlay dir {parent}: {mkdir.stderr.strip()[-300:]}",
                )
        if item.kind == "json":
            body = json.dumps(item.payload, indent=2, ensure_ascii=False) + "\n"
        else:
            body = str(item.payload)
        tmp_dir = Path(tempfile.mkdtemp(prefix="ageval-acp-overlay-"))
        tmp = tmp_dir / Path(dest).name
        try:
            tmp.write_text(body, encoding="utf-8")
            await host.upload(tmp, f"{HOME_PATH}/{dest}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        written.append(dest)
    return written


async def _copy_keyless_auth(host: Any, descriptor: AcpEntryDescriptor) -> list[str]:
    """Copy the host auth files this entry declared, when they are present."""
    host_home = Path.home()
    copied: list[str] = []
    for rel in descriptor.keyless_auth_paths:
        source = host_home / rel
        if source.is_symlink():
            raise EnvironmentFailure(
                "acp_auth_path_symlink",
                f"refusing to copy symlinked auth path {rel}",
            )
        if not source.is_file():
            continue
        await host.upload(source, f"{HOME_PATH}/{rel}")
        copied.append(rel)
    return copied
