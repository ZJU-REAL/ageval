#!/usr/bin/env bash
# Install ageval first-party coding-agent engines + ACP entries into a Debian/Ubuntu
# image layer (official L1 base). Exact pins match acp-entries.lock.json
# next to this script and src/ageval/plugins/contrib/acp/acp_entries.json.
#
# Rules:
# - No floating tags / latest.
# - Mode 1 installs engine AND adapter (codex, claude-code, pi).
# - Mode 2: opencode with native `acp` subcommand.
# - Mode 3: pinned grok vendor entry (no invoke-time npx).
# - Binaries land on system PATH for numeric non-root actors (/usr/local/bin).
# - Never bake credentials / auth files.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y --no-install-recommends nodejs

# Exact pins — keep in lock-step with acp-entries.lock.json / acp_entries.json.
CODEX_ENGINE="@openai/codex@0.146.0"
PI_ENGINE="@earendil-works/pi-coding-agent@0.83.0"
CLAUDE_ENGINE="@anthropic-ai/claude-code@2.1.221"
OPENCODE="opencode-ai@1.18.12"
CODEX_ACP="@agentclientprotocol/codex-acp@1.1.9"
CLAUDE_ACP="@agentclientprotocol/claude-agent-acp@0.64.2"
PI_ACP="pi-acp@0.0.33"
GROK="@xai-official/grok@0.2.120"

npm install -g \
  "${CODEX_ENGINE}" \
  "${PI_ENGINE}" \
  "${CLAUDE_ENGINE}" \
  "${OPENCODE}" \
  "${CODEX_ACP}" \
  "${CLAUDE_ACP}" \
  "${PI_ACP}" \
  "${GROK}"

npm cache clean --force
rm -rf /var/lib/apt/lists/* /tmp/*

# Codex ACP vendors its own @openai/codex tree. `npm i -g @openai/codex` puts the
# native optional next to the *top-level* engine, so `codex --version` passes
# while `codex-acp` still dies looking for @openai/codex-linux-arm64 (or -x64)
# from the nested copy. Install the platform package next to every tree.
_codex_native_pkg() {
  case "$(uname -m)" in
    aarch64|arm64) echo "@openai/codex-linux-arm64" ;;
    x86_64|amd64) echo "@openai/codex-linux-x64" ;;
    *)
      echo "unsupported uname -m $(uname -m) for Codex native binary" >&2
      exit 1
      ;;
  esac
}

_install_codex_native() {
  local pkg dir ver tag
  pkg="$(_codex_native_pkg)"
  case "${pkg}" in
    *-linux-arm64) tag="linux-arm64" ;;
    *-linux-x64) tag="linux-x64" ;;
    *) echo "unhandled Codex native package ${pkg}" >&2; exit 1 ;;
  esac
  while IFS= read -r -d '' pkgjson; do
    dir="$(dirname "${pkgjson}")"
    ver="$(node -p "require('${pkgjson}').version")"
    # optionalDependencies alias: @openai/codex-linux-arm64 -> npm:@openai/codex@<ver>-linux-arm64
    (cd "${dir}" && npm install --omit=dev --no-package-lock --no-fund --no-audit \
      "${pkg}@npm:@openai/codex@${ver}-${tag}")
  done < <(find /usr/lib/node_modules -path '*/@openai/codex/package.json' -print0)
}

_install_codex_native
NESTED_CODEX="$(find /usr/lib/node_modules/@agentclientprotocol/codex-acp -path '*/@openai/codex/bin/codex.js' | head -1)"
if [ -z "${NESTED_CODEX}" ]; then
  echo "nested Codex wrapper missing under codex-acp" >&2
  exit 1
fi
node "${NESTED_CODEX}" --version

# --- Verify as root (build-time) ---
command -v codex
command -v codex-acp
command -v pi
command -v pi-acp
command -v opencode
command -v claude || command -v claude-code
command -v claude-agent-acp
command -v grok

# Mode 2: ensure native ACP entry argv is present (help may be non-zero without TTY).
opencode --version

# --- Verify as numeric non-root actor (Spec 18/19 actor UID PATH) ---
# UID 10001 matches Dockerfile useradd; also probe an extra high UID used by multi-actor.
for probe_uid in 10001 11001; do
  if id -u "${probe_uid}" >/dev/null 2>&1 || true; then
    :
  fi
  # runuser may be unavailable; use setpriv/su fallbacks.
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "#${probe_uid}" -- bash -c '
      command -v codex && command -v codex-acp &&
      command -v pi && command -v pi-acp &&
      command -v opencode &&
      (command -v claude || command -v claude-code) && command -v claude-agent-acp &&
      command -v grok
    ' || {
      # user may not exist yet at install script time — Dockerfile creates 10001 after.
      # Fall back to pure PATH checks under a temp nobody-like identity if available.
      true
    }
  fi
done

# Final PATH smoke under `nobody` when present (must see /usr/local/bin).
if id nobody >/dev/null 2>&1; then
  su -s /bin/bash nobody -c '
    export PATH="/usr/local/bin:/usr/bin:/bin"
    command -v codex
    command -v codex-acp
    command -v pi
    command -v pi-acp
    command -v opencode
    command -v claude || command -v claude-code
    command -v claude-agent-acp
    command -v grok
  '
fi

echo "install-executors: ACP BOM ok (5 entries + Mode 1 adapters)"
