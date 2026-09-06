"""Render the ACP plugin bake Dockerfile for one bound ``options.entry``.

Pins and detect names stay in ``acp_entries.json``. The template is a
Dockerfile; this module only substitutes the bound entry. No floating ``npx``.
"""

from __future__ import annotations

from ageval.plugins.contrib.acp.hooks import _needed_commands
from ageval.plugins.contrib.acp.registry import get_entry
from ageval.plugins.errors import ExtensionMaterializeError

PACKAGES_MARKER = "__ACP_ENTRY_PACKAGES__"
DETECT_MARKER = "__ACP_DETECT_BINARIES__"

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
    descriptor = get_entry(entry_id)
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
    packages = _npm_packages(descriptor.install_command)
    names = _needed_commands(descriptor)
    if not names:
        raise ExtensionMaterializeError(
            f"acp entry {descriptor.entry_id!r} declares no detect commands",
            kind="extension_materialize_failed",
        )
    detect = " && ".join(f"command -v {name}" for name in names)
    body = template.replace(PACKAGES_MARKER, packages).replace(DETECT_MARKER, detect)
    if descriptor.entry_id == "codex":
        body = body.rstrip() + "\n" + _CODEX_NATIVE_RUN.lstrip("\n")
    return body


def _npm_packages(install_command: str) -> str:
    text = install_command.strip()
    prefix = "npm install -g "
    if not text.startswith(prefix):
        raise ExtensionMaterializeError(
            "acp install_command must be npm install -g <pinned packages>",
            kind="extension_materialize_failed",
        )
    packages = text[len(prefix) :].strip()
    tokens = packages.split()
    if not tokens or "npx" in tokens or any(tok.endswith("@latest") for tok in tokens):
        raise ExtensionMaterializeError(
            "acp install_command rejects floating npx / latest",
            kind="extension_materialize_failed",
        )
    return packages
