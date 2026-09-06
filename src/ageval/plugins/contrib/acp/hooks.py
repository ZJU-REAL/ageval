"""ACP ``after_environment_ready`` hook: probe the box, install only if missing.

The recipe comes from ``acp_entries.json``. A hit is the binary name and one
cheap stdio ``initialize``. Docker already baked the bound ``options.entry``
into the task image at ``host.start()``; a matching bake skips
``install_command``. A same-named binary that speaks TCP ACP does not.
"""

from __future__ import annotations

import json
import shlex
from typing import Any

from ageval.environments.protocol import HOME_PATH, EnvironmentFailure
from ageval.plugins.contrib.acp.child_env import entry_credentials_missing
from ageval.plugins.contrib.acp.home import home_env
from ageval.plugins.contrib.acp.registry import AcpEntryDescriptor, get_entry
from ageval.plugins.errors import ExtensionMaterializeError
from ageval.plugins.protocol import NextFn

# Runs before the task's own setup.sh (500) and after cheaper box preparation.
ENSURE_RUNTIME_PRIORITY = 100


def _box_host(ctx: Any) -> Any:
    """The environment service when rebound (evaluate host), else Attempt host."""
    services = getattr(ctx, "services", None)
    getter = getattr(services, "get", None)
    if callable(getter):
        found = getter("environment")
        if found is not None:
            return found
    return ctx.host


_HANDSHAKE_TIMEOUT_SEC = 8
_PROBE_EXEC_TIMEOUT_SEC = 90
_PROTOCOL_VERSION = 1

# In-box stdlib probe. Parent execs this via host.python_command; it must not
# import ageval. Name + pin first; initialize only when those already match,
# so a wrong-version TCP binary does not eat the handshake timeout.
_PROBE_SOURCE = r"""
import json, os, select, shutil, subprocess, sys, time

def _pins(cfg):
    out = []
    for pkg, pin in cfg.get("pins") or []:
        found = None
        try:
            proc = subprocess.run(
                ["npm", "ls", "-g", "--depth=0", "--json", pkg],
                capture_output=True, text=True, timeout=20,
            )
            data = json.loads(proc.stdout or "{}")
            info = (data.get("dependencies") or {}).get(pkg) or {}
            found = info.get("version")
        except Exception:
            found = None
        out.append({"package": pkg, "wanted": pin, "found": found, "ok": found == pin})
    return out

def _handshake(command, payload, timeout):
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__}
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        proc.stdin.flush()
        deadline = time.monotonic() + float(timeout)
        buf = b""
        fd = proc.stdout.fileno()
        while time.monotonic() < deadline:
            remain = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([fd], [], [], min(0.2, remain))
            if not ready:
                if proc.poll() is not None:
                    break
                continue
            chunk = os.read(fd, 8192)
            if not chunk:
                break
            buf += chunk
            if len(buf) > 65536:
                buf = buf[-65536:]
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip().lstrip(b"\x00\x01\x02\x03")
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except Exception:
                    continue
                if (
                    isinstance(msg, dict)
                    and msg.get("id") == 1
                    and ("result" in msg or "error" in msg)
                ):
                    return {"ok": True, "reason": "jsonrpc"}
        return {"ok": False, "reason": "no_jsonrpc_result"}
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass

cfg = json.loads(sys.argv[1])
wanted = list(cfg.get("wanted") or [])
missing = [name for name in wanted if not shutil.which(name)]
# Bake-in: binary + initialize is enough. npm ls -g is slow and the
# unprivileged sandbox cannot npm i -g when the pin check fails.
versions = []
init = {"ok": False, "reason": "skipped"}
if not missing:
    init = _handshake(
        list(cfg.get("acp_command") or []),
        cfg.get("payload") or {},
        cfg.get("handshake_timeout_sec") or 8,
    )
ok = (not missing) and bool(init.get("ok"))
sys.stdout.write(json.dumps({
    "ok": ok,
    "missing": missing,
    "versions": versions,
    "initialize": init,
}))
"""


def ensure_runtime(**kwargs: Any) -> Any:
    """Factory: bind the entry and its credential locator, return the handler."""
    options = dict(kwargs.get("options") or {})
    entry_id = str(options.get("entry") or "").strip()
    if not entry_id:
        raise ExtensionMaterializeError(
            "acp_entry_required",
            kind="extension_materialize_failed",
        )
    descriptor = get_entry(entry_id)
    if descriptor is None:
        raise ExtensionMaterializeError(
            f"unknown acp entry: {entry_id!r}",
            kind="extension_materialize_failed",
        )
    api_key_env = kwargs.get("api_key")

    async def _handler(ctx: Any, value: Any, nxt: NextFn) -> Any:
        await _prepare_attempt_home(ctx, descriptor, api_key_env=api_key_env)
        await _ensure_entry_present(ctx, descriptor)
        return await nxt(value)

    return _handler


async def _prepare_attempt_home(
    ctx: Any,
    descriptor: AcpEntryDescriptor,
    *,
    api_key_env: str | None,
) -> None:
    """Give the entry its own HOME, and refuse to run it with no credential.

    An entry authenticates either from a file it declared (BYOA) or from a host
    env name it declared (BYOK). With neither, this fails once here — before any
    Agent effect — instead of letting the entry start and time out on auth.
    """
    from ageval.plugins.contrib.acp.home import prepare_home

    remaining = ctx.remaining_seconds()
    home_timeout = 120.0 if remaining is None else max(float(remaining), 120.0)
    prepared = await prepare_home(
        _box_host(ctx),
        descriptor,
        timeout_sec=home_timeout,
    )
    auth_files = prepared["auth_files"]
    overlay_files = await _write_lock_overlays(ctx, descriptor, timeout_sec=home_timeout)
    ctx.record_fact(
        "acp_home_prepared",
        {
            "entry": descriptor.entry_id,
            "auth_files": auth_files,
            "lock_overlay_files": overlay_files,
        },
    )
    if not auth_files and entry_credentials_missing(
        descriptor.credential_env_names,
        api_key_env=api_key_env,
    ):
        raise EnvironmentFailure(
            "acp_credentials_missing",
            f"acp entry {descriptor.entry_id!r} has neither a declared auth file on this "
            f"host nor any of {list(descriptor.credential_env_names)} set",
        )


async def _write_lock_overlays(
    ctx: Any,
    descriptor: AcpEntryDescriptor,
    *,
    timeout_sec: float | None,
) -> list[str]:
    """Materialize engine overlays from the locked job. No host HOME copy."""
    from ageval.plugins.contrib.acp.home import write_lock_overlays
    from ageval.plugins.contrib.acp.lock_overlay import overlays_for_entry

    lock = getattr(ctx, "lock", None)
    job_overlay = getattr(lock, "job_overlay", None) if lock is not None else None
    files = overlays_for_entry(descriptor.entry_id, job_overlay)
    if not files:
        return []
    written = await write_lock_overlays(
        _box_host(ctx),
        files,
        timeout_sec=timeout_sec,
    )
    ctx.record_fact(
        "acp_lock_overlay_written",
        {"entry": descriptor.entry_id, "files": written},
    )
    return written


async def _ensure_entry_present(ctx: Any, descriptor: AcpEntryDescriptor) -> None:
    probe = await _run_probe(ctx, descriptor)
    ctx.record_fact("acp_runtime_probe", {"entry": descriptor.entry_id, **probe})
    if probe.get("ok"):
        return
    missing = probe.get("missing")
    if not isinstance(missing, list):
        missing = _needed_commands(descriptor)
    if not missing:
        raise EnvironmentFailure(
            "acp_runtime_missing",
            f"acp entry {descriptor.entry_id!r} failed runtime probe "
            f"({_probe_reason(probe)}) with binaries on PATH; not installing",
        )
    if not descriptor.install_command:
        raise EnvironmentFailure(
            "acp_runtime_missing",
            f"acp entry {descriptor.entry_id!r} failed runtime probe "
            f"({_probe_reason(probe)}) and declares no install command",
        )
    result = await _box_host(ctx).exec(
        ["bash", "-lc", _install_line(descriptor.install_command)],
        timeout_sec=ctx.remaining_seconds(),
    )
    ctx.record_fact(
        "acp_runtime_install",
        {"entry": descriptor.entry_id, "exit_code": result.exit_code},
    )
    if result.exit_code != 0:
        detail = (result.stderr or result.stdout or "").strip()[-500:]
        raise EnvironmentFailure(
            "acp_runtime_install_failed",
            f"installing acp entry {descriptor.entry_id!r} exited {result.exit_code}: {detail}",
        )
    again = await _run_probe(ctx, descriptor)
    ctx.record_fact("acp_runtime_probe_after_install", {"entry": descriptor.entry_id, **again})
    if not again.get("ok"):
        raise EnvironmentFailure(
            "acp_runtime_missing",
            f"acp entry {descriptor.entry_id!r} still failing runtime probe "
            f"after install ({_probe_reason(again)})",
        )


def _install_line(install_command: str) -> str:
    """Run the entry recipe as the box user; same recipe under passwordless sudo.

    Cloud snapshots often ship npm on a prefix the sandbox user cannot write.
    The recipe stays on the ACP entry; sudo is only the privilege to apply it.
    """
    quoted = shlex.quote(install_command)
    return f'({install_command}) || sudo -n env PATH="$PATH" bash -lc {quoted}'


def _needed_commands(descriptor: AcpEntryDescriptor) -> list[str]:
    """First detect command of each family the entry needs inside the box."""
    names: list[str] = []
    if descriptor.integration_mode == 1 and descriptor.engine_detect_commands:
        names.append(descriptor.engine_detect_commands[0])
    if descriptor.acp_detect_commands:
        names.append(descriptor.acp_detect_commands[0])
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        token = name.strip().split()[0] if name.strip() else ""
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _pinned_packages(descriptor: AcpEntryDescriptor) -> list[tuple[str, str]]:
    """Unique (package, version) pins the probe must observe via ``npm ls -g``."""
    pins: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pkg, ver in (
        (descriptor.acp_package, descriptor.acp_version),
        (descriptor.engine_package, descriptor.engine_version),
    ):
        if not pkg or not ver:
            continue
        item = (str(pkg), str(ver))
        if item in seen:
            continue
        seen.add(item)
        pins.append(item)
    return pins


def _probe_config(descriptor: AcpEntryDescriptor) -> dict[str, Any]:
    return {
        "wanted": _needed_commands(descriptor),
        "pins": [list(item) for item in _pinned_packages(descriptor)],
        "acp_command": list(descriptor.acp_command),
        "handshake_timeout_sec": _HANDSHAKE_TIMEOUT_SEC,
        "payload": {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "clientInfo": {"name": "ageval-probe", "version": "0"},
                "capabilities": {},
            },
        },
    }


def _probe_argv(host: Any, descriptor: AcpEntryDescriptor) -> list[str]:
    python = [str(part) for part in getattr(host, "python_command", ()) or ("python3",)]
    return [
        *python,
        "-c",
        _PROBE_SOURCE,
        json.dumps(_probe_config(descriptor), separators=(",", ":")),
    ]


def _parse_probe_stdout(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "ok" in data:
            return data
    return {"ok": False, "reason": "unparseable_probe"}


def _probe_reason(probe: dict[str, Any]) -> str:
    if probe.get("reason"):
        return str(probe["reason"])
    missing = probe.get("missing") or []
    if missing:
        return f"missing {missing}"
    bad_pins = [
        f"{row.get('package')}@{row.get('found') or 'missing'}!={row.get('wanted')}"
        for row in (probe.get("versions") or [])
        if isinstance(row, dict) and not row.get("ok")
    ]
    if bad_pins:
        return "version " + ", ".join(bad_pins)
    raw_init = probe.get("initialize")
    init: dict[str, Any] = raw_init if isinstance(raw_init, dict) else {}
    return f"initialize {init.get('reason') or 'failed'}"


def _probe_env(host: Any, descriptor: AcpEntryDescriptor) -> dict[str, str]:
    """HOME the entry will use at attach_stdio. Probe initialize writes XDG dirs."""
    visible = getattr(host, "visible_path", None)
    home = str(visible(HOME_PATH) if callable(visible) else HOME_PATH)
    env = home_env(descriptor, home)
    for key, value in descriptor.fixed_env.items():
        if value:
            env[str(key)] = str(value)
    return env


async def _run_probe(ctx: Any, descriptor: AcpEntryDescriptor) -> dict[str, Any]:
    host = _box_host(ctx)
    timeout = min(float(ctx.remaining_seconds()), float(_PROBE_EXEC_TIMEOUT_SEC))
    try:
        result = await host.exec(
            _probe_argv(host, descriptor),
            timeout_sec=timeout,
            env=_probe_env(host, descriptor),
        )
    except Exception as exc:  # noqa: BLE001 — probe is fail-closed
        return {"ok": False, "reason": type(exc).__name__, "missing": _needed_commands(descriptor)}
    parsed = _parse_probe_stdout(result.stdout)
    if parsed.get("reason") == "unparseable_probe" and result.exit_code != 0:
        parsed["exit_code"] = result.exit_code
    return parsed
