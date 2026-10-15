"""Render the ACP plugin bake Dockerfile for one bound ``options.entry``.

Pins and detect names stay in ``acp_entries.json``. The template is a
Dockerfile; this module only substitutes the bound entry. No floating ``npx``.
"""

from __future__ import annotations

import json
import shlex

from ageval.plugins.contrib.acp.hooks import required_bins
from ageval.plugins.contrib.acp.registry import AcpRegistryError, get_entry, pinned_npm_packages
from ageval.plugins.errors import ExtensionMaterializeError

PACKAGES_MARKER = "__ACP_ENTRY_PACKAGES__"
DETECT_MARKER = "__ACP_DETECT_BINARIES__"

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


def _realpath_check(required: list[tuple[str, str]]) -> str:
    payload = json.dumps(
        [{"name": name, "package": package} for name, package in required],
        separators=(",", ":"),
    )
    return "node -e " + shlex.quote(_PIN_CHECK_JS) + " " + shlex.quote(payload)


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
    if PACKAGES_MARKER not in template or DETECT_MARKER not in template:
        raise ExtensionMaterializeError(
            "acp bake template missing package or detect marker",
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
    body = template.replace(PACKAGES_MARKER, packages).replace(DETECT_MARKER, detect)
    if descriptor.entry_id == "codex":
        body = body.rstrip() + "\n" + _CODEX_NATIVE_RUN.lstrip("\n")
    return body
