"""Render the ACP plugin bake Dockerfile for one bound ``options.entry``.

Pins, detect names, and ``runtime.node`` stay in ``acp_entries.json``. The
template is a Dockerfile; this module only substitutes the bound entry.
No floating ``npx``.
"""

from __future__ import annotations

import json
import shlex

from ageval.plugins.contrib.acp.hooks import required_bins
from ageval.plugins.contrib.acp.registry import AcpRegistryError, get_entry, pinned_npm_packages
from ageval.plugins.errors import ExtensionMaterializeError

PACKAGES_MARKER = "__ACP_ENTRY_PACKAGES__"
DETECT_MARKER = "__ACP_DETECT_BINARIES__"
NODE_GATE_MARKER = "__ACP_NODE_GATE__"
# NodeSource major this bake knows how to install. A higher floor fails closed.
NODE_INSTALL_MAJOR = 22

# Required-name realpath against the package bin. Not a bare PATH existence check.
_PIN_CHECK_JS = r"""
const fs = require("fs");
const path = require("path");
const {execFileSync} = require("child_process");
const root = execFileSync("npm", ["root", "-g"], {encoding: "utf8"}).trim();
const required = JSON.parse(process.argv[1]);
function real(target) { return fs.realpathSync(target); }
function which(name) {
  const dirs = (process.env.PATH || "").split(path.delimiter);
  for (const dir of dirs) {
    if (!dir) continue;
    const candidate = path.join(dir, name);
    try {
      if (fs.existsSync(candidate)) return real(candidate);
    } catch (err) { continue; }
  }
  return "";
}
function unscoped(pkg) { return pkg.split("/").pop(); }
for (const item of required) {
  const pkgdir = path.join(root, item.package);
  const manifest = JSON.parse(fs.readFileSync(path.join(pkgdir, "package.json"), "utf8"));
  let rel = "";
  if (typeof manifest.bin === "string") {
    if (item.name !== unscoped(item.package)) process.exit(1);
    rel = manifest.bin;
  } else if (manifest.bin && typeof manifest.bin === "object") {
    const declared = manifest.bin[item.name];
    if (typeof declared === "string") rel = declared;
  }
  if (!rel) process.exit(1);
  const expected = real(path.resolve(pkgdir, rel));
  const actual = which(item.name);
  if (!actual || actual !== expected) process.exit(1);
}
"""


def _js_one_line(source: str) -> str:
    """Dockerfile RUN is one instruction. A newline inside the script starts a new one."""
    return " ".join(part.strip() for part in source.splitlines() if part.strip())


def _shell_one_line(source: str) -> str:
    """Join a POSIX script so a Dockerfile RUN does not start a new instruction.

    Newlines are command separators here. ``{``, ``then``, and ``do`` stay
    open, so the next line is a space rather than ``;``.
    """
    parts = [part.strip() for part in source.splitlines() if part.strip()]
    if not parts:
        return ""
    chunks = [parts[0]]
    for part in parts[1:]:
        sep = " " if chunks[-1].endswith(("{", "then", "do", "else")) else "; "
        chunks.append(sep + part)
    return "".join(chunks)


# POSIX sh. npm on PATH is not a version. Collapsed onto one RUN line.
_NODE_GATE_SH = r"""
set -eu
entry_id=__ENTRY_ID__
floor=__NODE_FLOOR__
install_major=__NODE_INSTALL_MAJOR__
node_meets() {
  bare="$1"
  need="$2"
  bare="${bare#v}"
  bare="${bare#V}"
  bare="${bare%%-*}"
  case "$bare" in ""|missing) return 1 ;; esac
  oldifs=$IFS
  IFS=.
  set -- $bare
  a1=${1:-0}
  a2=${2:-0}
  a3=${3:-0}
  set -- $need
  b1=${1:-0}
  b2=${2:-0}
  b3=${3:-0}
  IFS=$oldifs
  for part in "$a1" "$a2" "$a3" "$b1" "$b2" "$b3"; do
    case "$part" in ""|*[!0-9]*) return 1 ;; esac
  done
  if [ "$a1" -gt "$b1" ]; then return 0; fi
  if [ "$a1" -lt "$b1" ]; then return 1; fi
  if [ "$a2" -gt "$b2" ]; then return 0; fi
  if [ "$a2" -lt "$b2" ]; then return 1; fi
  [ "$a3" -ge "$b3" ]
}
read_node() {
  if ! command -v node >/dev/null 2>&1; then
    printf '%s' missing
    return 0
  fi
  found="$(node -v 2>/dev/null || true)"
  printf '%s' "${found:-missing}"
}
fail_floor() {
  echo "acp entry ${entry_id} requires node >=${floor}; found ${found}$1" >&2
  exit 1
}
found="$(read_node)"
if node_meets "$found" "$floor"; then
  exit 0
fi
floor_major="${floor%%.*}"
if [ "$floor_major" -gt "$install_major" ]; then
  fail_floor "; bake installs node ${install_major}.x only"
fi
install_node() {
  export DEBIAN_FRONTEND=noninteractive
  if ! command -v apt-get >/dev/null 2>&1; then
    return 1
  fi
  apt-get update || return 1
  apt-get install -y --no-install-recommends ca-certificates curl gnupg || return 1
  curl -fsSL "https://deb.nodesource.com/setup_${install_major}.x" | bash - || return 1
  apt-get install -y --no-install-recommends nodejs || return 1
  rm -rf /var/lib/apt/lists/* || return 1
  hash -r 2>/dev/null || true
  return 0
}
if ! install_node; then
  fail_floor ""
fi
found="$(read_node)"
if node_meets "$found" "$floor"; then
  exit 0
fi
fail_floor ""
"""


def node_gate_script(entry_id: str, floor: tuple[int, int, int]) -> str:
    """One-line POSIX script: install Node 22.x or fail when *floor* is unmet."""
    spec = ".".join(str(part) for part in floor)
    script = (
        _NODE_GATE_SH.replace("__ENTRY_ID__", shlex.quote(entry_id), 1)
        .replace("__NODE_FLOOR__", shlex.quote(spec), 1)
        .replace("__NODE_INSTALL_MAJOR__", shlex.quote(str(NODE_INSTALL_MAJOR)), 1)
    )
    return _shell_one_line(script)


def _realpath_check(required: list[tuple[str, str]]) -> str:
    payload = json.dumps(
        [{"name": name, "package": package} for name, package in required],
        separators=(",", ":"),
    )
    return "node -e " + shlex.quote(_js_one_line(_PIN_CHECK_JS)) + " " + shlex.quote(payload)


# BuildKit runs a shell-form RUN as `/bin/sh -c` (dash on ubuntu/debian). This
# loop uses bash process substitution, so switch SHELL for the remaining RUNs.
# Official Attempt base runs the same logic under `bash /tmp/install-executors.sh`.
_CODEX_NATIVE_RUN = r"""
# Codex ACP vendors a nested @openai/codex; the platform native must sit next to it.
SHELL ["/bin/bash", "-c"]
RUN set -eu; \
    case "$(uname -m)" in \
      aarch64|arm64) pkg="@openai/codex-linux-arm64"; tag="linux-arm64" ;; \
      x86_64|amd64) pkg="@openai/codex-linux-x64"; tag="linux-x64" ;; \
      *) echo "unsupported uname -m $(uname -m) for Codex native binary" >&2; exit 1 ;; \
    esac; \
    while IFS= read -r -d '' pkgjson; do \
      dir="$(dirname "${pkgjson}")"; \
      ver="$(node -p "require('${pkgjson}').version")"; \
      (cd "${dir}" && npm install --omit=dev --no-package-lock --no-fund --no-audit \
        "${pkg}@npm:@openai/codex@${ver}-${tag}"); \
    done < <(find /usr/lib/node_modules -path '*/@openai/codex/package.json' -print0)
"""


def render_bake_body(template: str, entry_id: str) -> str:
    """Fill the bake template with the pinned packages for *entry_id*."""
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
    if (
        PACKAGES_MARKER not in template
        or DETECT_MARKER not in template
        or NODE_GATE_MARKER not in template
    ):
        raise ExtensionMaterializeError(
            "acp bake template missing package, detect, or node gate marker",
            kind="extension_materialize_failed",
        )
    try:
        packages = pinned_npm_packages(descriptor.install_command)
    except AcpRegistryError as exc:
        raise ExtensionMaterializeError(
            str(exc),
            kind="extension_materialize_failed",
        ) from exc
    required = required_bins(descriptor)
    if not required:
        raise ExtensionMaterializeError(
            f"acp entry {descriptor.entry_id!r} declares no pinned binaries",
            kind="extension_materialize_failed",
        )
    detect = _realpath_check(required)
    gate = node_gate_script(descriptor.entry_id, descriptor.runtime.node)
    body = (
        template.replace(NODE_GATE_MARKER, gate)
        .replace(PACKAGES_MARKER, packages)
        .replace(DETECT_MARKER, detect)
    )
    if descriptor.entry_id == "codex":
        body = body.rstrip() + "\n" + _CODEX_NATIVE_RUN.lstrip("\n")
    return body
