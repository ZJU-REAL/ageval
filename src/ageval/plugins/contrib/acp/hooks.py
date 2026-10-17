"""ACP ``after_environment_ready`` hook: probe the box, install only on a pin miss.

A hit is ``npm ls -g --depth=0`` version equality, the required command's
realpath equal to that package's bin, and one stdio ``initialize`` whose
argv[0] is that absolute path. A version or realpath miss installs once.
"""

from __future__ import annotations

import json
import shlex
from typing import Any

from ageval.environments.protocol import HOME_PATH, EnvironmentFailure
from ageval.plugins.contrib.acp.child_env import entry_credentials_missing
from ageval.plugins.contrib.acp.home import home_env
from ageval.plugins.contrib.acp.registry import AcpEntryDescriptor, AcpRegistryError, get_entry
from ageval.plugins.errors import ExtensionMaterializeError
from ageval.plugins.protocol import NextFn
from ageval.runtime.clocks import clock_default

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
# import ageval. Version and required-bin realpath first; initialize only
# when both already match, and argv[0] is that absolute path.
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

def _npm_root():
    try:
        proc = subprocess.run(
            ["npm", "root", "-g"],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return ""
    return (proc.stdout or "").strip()

def _which_real(name):
    found = shutil.which(name)
    if not found:
        return ""
    try:
        return os.path.realpath(found)
    except Exception:
        return ""

def _unscoped(package):
    return package.rsplit("/", 1)[-1]

def _package_bin(root, package, name):
    if not root or not package or not name:
        return ""
    pkg_dir = os.path.join(root, package)
    try:
        with open(os.path.join(pkg_dir, "package.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception:
        return ""
    declared = manifest.get("bin")
    rel = None
    if isinstance(declared, str):
        if name != _unscoped(package):
            return ""
        rel = declared
    elif isinstance(declared, dict):
        candidate = declared.get(name)
        if isinstance(candidate, str):
            rel = candidate
    if not rel:
        return ""
    try:
        return os.path.realpath(os.path.join(pkg_dir, rel))
    except Exception:
        return ""

cfg = json.loads(sys.argv[1])
root = _npm_root()
versions = _pins(cfg)
declared_pins = list(cfg.get("pins") or [])
pins_ok = bool(declared_pins) and len(versions) == len(declared_pins) and all(
    row.get("ok") for row in versions
)
missing = []
resolved = {}
for item in cfg.get("required") or []:
    name = str(item.get("name") or "")
    package = str(item.get("package") or "")
    expected = _package_bin(root, package, name)
    actual = _which_real(name)
    if not expected or not actual or expected != actual:
        missing.append(name)
    else:
        resolved[name] = actual
acp_command = [str(part) for part in (cfg.get("acp_command") or [])]
argv0 = resolved.get(acp_command[0]) if acp_command else None
paths_ok = (not missing) and bool(argv0)
init = {"ok": False, "reason": "skipped"}
if pins_ok and paths_ok and not cfg.get("skip_handshake"):
    init = _handshake(
        [argv0, *acp_command[1:]],
        cfg.get("payload") or {},
        cfg.get("handshake_timeout_sec") or 8,
    )
ok = pins_ok and paths_ok and (bool(init.get("ok")) or bool(cfg.get("skip_handshake")))
sys.stdout.write(json.dumps({
    "ok": ok,
    "missing": missing,
    "versions": versions,
    "initialize": init,
    "argv0": argv0,
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
    try:
        descriptor = get_entry(entry_id)
    except AcpRegistryError as exc:
        raise ExtensionMaterializeError(
            str(exc),
            kind="extension_materialize_failed",
        ) from exc
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

    if _phase_clock_out(ctx):
        token = _clock_token(ctx)
        raise EnvironmentFailure(token, token)
    remaining = ctx.remaining_seconds()
    cap = clock_default("acp_home_cap")
    home_timeout = cap if remaining is None else min(cap, float(remaining))
    try:
        prepared = await prepare_home(
            _box_host(ctx),
            descriptor,
            timeout_sec=home_timeout,
        )
    except EnvironmentFailure as exc:
        if _phase_clock_out(ctx):
            token = _clock_token(ctx)
            raise EnvironmentFailure(token, token) from exc
        raise
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
    if _phase_clock_out(ctx):
        token = _clock_token(ctx)
        raise EnvironmentFailure(token, token)
    probe = await _run_probe(ctx, descriptor)
    ctx.record_fact("acp_runtime_probe", {"entry": descriptor.entry_id, **probe})
    if probe.get("ok"):
        _remember_argv0(ctx, descriptor.entry_id, probe.get("argv0"))
        return
    if not _needs_install(probe):
        raise EnvironmentFailure(
            "acp_runtime_missing",
            f"acp entry {descriptor.entry_id!r} failed runtime probe "
            f"({_probe_reason(probe)}) with the pinned binary; not installing",
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
        if _phase_clock_out(ctx):
            token = _clock_token(ctx)
            raise EnvironmentFailure(token, token)
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
    _remember_argv0(ctx, descriptor.entry_id, again.get("argv0"))


def _install_line(install_command: str) -> str:
    """Run the entry recipe as the box user; same recipe under passwordless sudo.

    Cloud snapshots often ship npm on a prefix the sandbox user cannot write.
    The recipe stays on the ACP entry; sudo is only the privilege to apply it.
    """
    quoted = shlex.quote(install_command)
    return f'({install_command}) || sudo -n env PATH="$PATH" bash -lc {quoted}'


def required_bins(descriptor: AcpEntryDescriptor) -> list[tuple[str, str]]:
    """``(command, package)`` pairs whose realpath must be that package's bin.

    Mode 1 checks the engine command and ``acp_command[0]``. Modes 2 and 3
    check only ``acp_command[0]``. Detect aliases are not required.
    """
    rows: list[tuple[str, str]] = []
    if descriptor.integration_mode == 1 and descriptor.engine_command and descriptor.engine_package:
        rows.append((descriptor.engine_command, descriptor.engine_package))
    if descriptor.acp_command and descriptor.acp_package:
        rows.append((descriptor.acp_command[0], descriptor.acp_package))
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for item in rows:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _needed_commands(descriptor: AcpEntryDescriptor) -> list[str]:
    """Required command names. Aliases in the detect lists are not included."""
    return [name for name, _package in required_bins(descriptor)]


_ARGV0_ATTR = "acp_entry_argv0"


def store_entry_argv0(host: Any, entry_id: str, argv0: str) -> None:
    """Remember the pinned absolute argv0 on the box the executor will attach to."""
    current = getattr(host, _ARGV0_ATTR, None)
    if not isinstance(current, dict):
        current = {}
        setattr(host, _ARGV0_ATTR, current)
    current[entry_id] = argv0


def stored_entry_argv0(host: Any, entry_id: str) -> str | None:
    current = getattr(host, _ARGV0_ATTR, None)
    if not isinstance(current, dict):
        return None
    value = current.get(entry_id)
    if isinstance(value, str) and value.startswith("/"):
        return value
    return None


def _remember_argv0(ctx: Any, entry_id: str, argv0: Any) -> None:
    if not isinstance(argv0, str) or not argv0.startswith("/"):
        return
    store_entry_argv0(_box_host(ctx), entry_id, argv0)
    bag = getattr(ctx, "acp_entry_argv0", None)
    if not isinstance(bag, dict):
        bag = {}
        ctx.acp_entry_argv0 = bag
    bag[entry_id] = argv0


def _needs_install(probe: dict[str, Any]) -> bool:
    """Version or required-bin miss installs once. A failed handshake does not."""
    if probe.get("ok"):
        return False
    versions = probe.get("versions")
    pins_ok = (
        isinstance(versions, list)
        and bool(versions)
        and all(isinstance(row, dict) and row.get("ok") for row in versions)
    )
    missing = probe.get("missing")
    argv0 = probe.get("argv0")
    paths_ok = (
        isinstance(missing, list)
        and not missing
        and isinstance(argv0, str)
        and argv0.startswith("/")
    )
    return not (pins_ok and paths_ok)


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


def _probe_config(
    descriptor: AcpEntryDescriptor,
    *,
    skip_handshake: bool = False,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "required": [
            {"name": name, "package": package} for name, package in required_bins(descriptor)
        ],
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
    if skip_handshake:
        config["skip_handshake"] = True
    return config


def _probe_argv(
    host: Any,
    descriptor: AcpEntryDescriptor,
    *,
    skip_handshake: bool = False,
) -> list[str]:
    python = [str(part) for part in getattr(host, "python_command", ()) or ("python3",)]
    return [
        *python,
        "-c",
        _PROBE_SOURCE,
        json.dumps(
            _probe_config(descriptor, skip_handshake=skip_handshake),
            separators=(",", ":"),
        ),
    ]


async def resolve_entry_argv0(host: Any, descriptor: AcpEntryDescriptor) -> str | None:
    """Re-check the pinned bin inside the box. No handshake, no PATH fallback."""
    try:
        result = await host.exec(
            _probe_argv(host, descriptor, skip_handshake=True),
            timeout_sec=float(_PROBE_EXEC_TIMEOUT_SEC),
            env=_probe_env(host, descriptor),
        )
    except Exception:  # noqa: BLE001 — resolve is fail-closed
        return None
    parsed = _parse_probe_stdout(getattr(result, "stdout", "") or "")
    argv0 = parsed.get("argv0")
    if _needs_install(parsed) or not isinstance(argv0, str) or not argv0.startswith("/"):
        return None
    return argv0


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


def _phase_clock_out(ctx: Any) -> bool:
    remaining = ctx.remaining_seconds()
    return isinstance(remaining, int | float) and not isinstance(remaining, bool) and remaining <= 0


def _clock_token(ctx: Any) -> str:
    """The budget token for whichever phase is on the clock."""
    if getattr(ctx, "phase", "") == "evaluate":
        return "evaluate_timeout"
    return "environment_timeout"


async def _run_probe(ctx: Any, descriptor: AcpEntryDescriptor) -> dict[str, Any]:
    host = _box_host(ctx)
    remaining = ctx.remaining_seconds()
    cap = float(_PROBE_EXEC_TIMEOUT_SEC)
    timeout = cap if not isinstance(remaining, int | float) else min(float(remaining), cap)
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
