"""Generate Attempt-HOME engine overlays from the locked job document.

ACP entries read config from the isolated Attempt HOME, not the operator
host. After lock, provider / model / locator / optional base_url are known;
``after_environment_ready`` writes the engine's own file so docker, local,
and other kinds bind the same id. Host ``~/.pi`` / ``~/.config`` is never
copied. Locator *values* never enter the file.

OpenCode's ``permission`` object is the exception to "same file everywhere".
A disposable evaluation container has no operator to answer an internal
``external_directory`` ask, so that kind gets an explicit allow policy.
``local`` and ``ssh`` keep OpenCode's own defaults.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ageval.config.errors import ConfigError
from ageval.environments.protocol import HOME_PATH

# Thrown away with the Attempt. ``local`` and ``ssh`` are persistent hosts.
DISPOSABLE_EVALUATION_KINDS = frozenset({"docker", "e2b", "daytona"})

# OpenCode 1.x key. ``*`` does not replace the named keys: ``external_directory``
# defaults to ask, and an agent rule can keep that ask when the key is omitted.
OPENCODE_V1_PERMISSION: dict[str, str] = {
    "*": "allow",
    "bash": "allow",
    "edit": "allow",
    "webfetch": "allow",
    "external_directory": "allow",
}

# OpenCode 2.x reads a ``permissions`` array. 1.x rejects that key, and this
# writer does not emit it. Any major other than 1 fails closed.
OPENCODE_PERMISSION_SCHEMA_UNSUPPORTED = "opencode_permission_schema_unsupported"

_SKIP_MODELS = frozenset({"", "entry-default"})


def _row_model_id(row: Mapping[str, Any]) -> str:
    from ageval.config.profiles import model_id

    return model_id(row.get("model"))


@dataclass(frozen=True, slots=True)
class OverlayFile:
    """One file relative to Attempt HOME."""

    dest: str
    payload: Any
    kind: str  # "json" | "toml"


def split_model(model: str) -> tuple[str | None, str]:
    """Split ``provider/id`` on the first slash. No slash → (None, id)."""
    text = model.strip()
    if "/" not in text:
        return None, text
    provider, _, rest = text.partition("/")
    provider = provider.strip()
    rest = rest.strip()
    if not provider or not rest:
        return None, text
    return provider, rest


def _entry_id(row: Mapping[str, Any]) -> str | None:
    options = row.get("options")
    if isinstance(options, Mapping) and "entry" in options:
        raw = options["entry"]
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    for ext in row.get("extensions") or ():
        if not isinstance(ext, Mapping):
            continue
        if str(ext.get("plugin") or "") != "acp":
            continue
        nested = ext.get("options")
        if isinstance(nested, Mapping) and "entry" in nested:
            raw = nested["entry"]
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None


def _profiles_for_entry(
    job_overlay: Mapping[str, Any] | None, entry_id: str
) -> list[Mapping[str, Any]]:
    if not isinstance(job_overlay, Mapping):
        return []
    profiles = job_overlay.get("agent_profiles")
    if not isinstance(profiles, Mapping):
        return []
    out: list[Mapping[str, Any]] = []
    for row in profiles.values():
        if isinstance(row, Mapping) and _entry_id(row) == entry_id:
            out.append(row)
    return out


def _locator_name(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("${") and text.endswith("}"):
        text = text[2:-1].strip()
    elif text.startswith("$"):
        text = text[1:].strip()
    return text or None


def _pi_api_key_ref(locator: str | None) -> str | None:
    if not locator:
        return None
    return f"${locator}"


def _opencode_env_ref(locator: str | None) -> str | None:
    if not locator:
        return None
    return f"{{env:{locator}}}"


def _codex_base_url(raw: Any) -> str | None:
    """Literal URL, or a locator name resolved from the environment.

    Codex config.toml has no env indirection for ``base_url``. An unset
    locator omits the key. Pi and OpenCode keep their own locator syntax.
    """
    from ageval.config.locator import parse_locked_base_url, resolve_if_set

    loc = parse_locked_base_url(raw)
    if loc is None:
        return None
    return resolve_if_set(loc)


def _is_http_url(raw: Any) -> bool:
    text = str(raw or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _pi_base_url(raw: Any) -> str | None:
    if raw is None or str(raw).strip() == "":
        return None
    if _is_http_url(raw):
        return str(raw).strip()
    loc = _locator_name(raw)
    return f"${{{loc}}}" if loc else None


def _opencode_base_url(raw: Any) -> str | None:
    if raw is None or str(raw).strip() == "":
        return None
    if _is_http_url(raw):
        return str(raw).strip()
    loc = _locator_name(raw)
    return _opencode_env_ref(loc)


def build_pi_overlays(rows: list[Mapping[str, Any]]) -> list[OverlayFile]:
    providers: dict[str, dict[str, Any]] = {}
    default_provider: str | None = None
    default_model: str | None = None
    for row in rows:
        model = _row_model_id(row)
        if model in _SKIP_MODELS:
            continue
        provider, model_id = split_model(model)
        if default_model is None:
            default_provider = provider
            default_model = model_id
        if provider is None:
            continue
        bucket = providers.setdefault(
            provider,
            {"models": []},
        )
        api_ref = _pi_api_key_ref(_locator_name(row.get("api_key")))
        if api_ref:
            bucket["apiKey"] = api_ref
        base = _pi_base_url(row.get("base_url"))
        if base:
            bucket["baseUrl"] = base
            bucket["api"] = "openai-completions"
        models: list[dict[str, str]] = bucket["models"]
        if not any(item.get("id") == model_id for item in models):
            models.append({"id": model_id, "name": model_id})
    files: list[OverlayFile] = []
    if providers:
        files.append(
            OverlayFile(
                dest=".pi/agent/models.json",
                payload={"providers": providers},
                kind="json",
            )
        )
    if default_model:
        settings: dict[str, str] = {"defaultModel": default_model}
        if default_provider:
            settings["defaultProvider"] = default_provider
        files.append(
            OverlayFile(
                dest=".pi/agent/settings.json",
                payload=settings,
                kind="json",
            )
        )
    return files


def is_disposable_evaluation_environment(kind: str | None) -> bool:
    """True when *kind* is a disposable evaluation container.

    An absent or unknown kind is not disposable. The allow policy is opt-in
    by this set, so a missing job field keeps OpenCode's defaults.
    """
    if not isinstance(kind, str):
        return False
    return kind.strip() in DISPOSABLE_EVALUATION_KINDS


def _environment_kind(job_overlay: Mapping[str, Any] | None) -> str:
    if not isinstance(job_overlay, Mapping):
        return ""
    kind = job_overlay.get("environment")
    return kind.strip() if isinstance(kind, str) else ""


def opencode_config_major(version: str | None) -> int | None:
    """Major of an OpenCode package version. ``None`` when it is not numeric."""
    if not isinstance(version, str):
        return None
    text = version.strip()
    if text[:1] in {"v", "V"}:
        text = text[1:]
    head = text.split(".", 1)[0]
    if not head.isdigit():
        return None
    return int(head)


def packaged_opencode_version() -> str | None:
    """Version of the packaged ``opencode`` entry, engine pin preferred."""
    from ageval.plugins.contrib.acp.registry import get_entry

    desc = get_entry("opencode")
    if desc is None:
        return None
    return desc.engine_version or desc.acp_version


def require_opencode_v1_permission_schema(version: str | None) -> None:
    """Refuse to write a v1 ``permission`` object for any other schema.

    OpenCode 1.x accepts ``permission``. OpenCode 2.x accepts a ``permissions``
    array, which 1.x rejects as an unrecognized key. Emitting either shape for
    the other major would be an invalid policy.
    """
    if opencode_config_major(version) == 1:
        return
    text = version.strip() if isinstance(version, str) else ""
    shown = text or "unknown"
    raise ConfigError(
        OPENCODE_PERMISSION_SCHEMA_UNSUPPORTED,
        f"OpenCode {shown} does not accept the v1 permission object "
        "(OpenCode 2.x uses a permissions array). Refusing to write opencode.json.",
        location="/environment",
    )


def validate_opencode_permission_schema(job_overlay: Mapping[str, Any] | None) -> None:
    """Lock gate: a disposable OpenCode run must be writable as v1 config.

    ``local`` and ``ssh`` do not receive the policy, so their OpenCode version
    is not checked here. An absent environment kind is treated as not disposable.
    """
    if not is_disposable_evaluation_environment(_environment_kind(job_overlay)):
        return
    if not _profiles_for_entry(job_overlay, "opencode"):
        return
    require_opencode_v1_permission_schema(packaged_opencode_version())


def build_opencode_overlays(
    rows: list[Mapping[str, Any]],
    *,
    environment: str | None = None,
) -> list[OverlayFile]:
    providers: dict[str, dict[str, Any]] = {}
    default_model: str | None = None
    for row in rows:
        model = _row_model_id(row)
        if model in _SKIP_MODELS:
            continue
        if default_model is None:
            default_model = model
        provider, model_id = split_model(model)
        if provider is None:
            continue
        bucket = providers.setdefault(
            provider,
            {
                "npm": "@ai-sdk/openai-compatible",
                "name": provider,
                "models": {},
            },
        )
        models = bucket["models"]
        if isinstance(models, dict) and model_id not in models:
            models[model_id] = {"name": model_id}
        api_ref = _opencode_env_ref(_locator_name(row.get("api_key")))
        base = _opencode_base_url(row.get("base_url"))
        options = dict(bucket.get("options") or {})
        if api_ref:
            options["apiKey"] = api_ref
        if base:
            options["baseURL"] = base
        if options:
            bucket["options"] = options
    disposable = is_disposable_evaluation_environment(environment)
    if default_model is None and not disposable:
        return []
    payload: dict[str, Any] = {"$schema": "https://opencode.ai/config.json"}
    if default_model is not None:
        payload["model"] = default_model
    if providers:
        payload["provider"] = providers
    if disposable:
        require_opencode_v1_permission_schema(packaged_opencode_version())
        payload["permission"] = dict(OPENCODE_V1_PERMISSION)
    return [
        OverlayFile(
            dest=".config/opencode/opencode.json",
            payload=payload,
            kind="json",
        )
    ]


def _toml_escape(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _codex_catalog_entry(slug: str) -> dict[str, Any]:
    """Catalog row Codex accepts (Z.ai Codex docs). slug must equal config `model`."""
    return {
        "slug": slug,
        "display_name": slug,
        "description": slug,
        "default_reasoning_level": "high",
        "supported_reasoning_levels": [
            {"effort": "low", "description": "Light reasoning"},
            {"effort": "high", "description": "Enhanced reasoning"},
            {"effort": "max", "description": "Deep reasoning"},
        ],
        "shell_type": "shell_command",
        "visibility": "list",
        "supported_in_api": True,
        "priority": 0,
        "base_instructions": "",
        "supports_reasoning_summaries": True,
        "default_reasoning_summary": "none",
        "support_verbosity": False,
        "apply_patch_tool_type": "freeform",
        "truncation_policy": {"mode": "bytes", "limit": 10000},
        "context_window": 1048576,
        "max_context_window": 1048576,
        "effective_context_window_percent": 95,
        "supports_parallel_tool_calls": True,
        "experimental_supported_tools": [],
        "input_modalities": ["text"],
    }


def build_codex_overlays(rows: list[Mapping[str, Any]]) -> list[OverlayFile]:
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    env_key: str | None = None
    for row in rows:
        raw = _row_model_id(row)
        if raw in _SKIP_MODELS:
            continue
        split_provider, model_id = split_model(raw)
        if model is None:
            model = model_id
            provider = split_provider
        loc = _locator_name(row.get("api_key"))
        if loc:
            env_key = loc
        resolved = _codex_base_url(row.get("base_url"))
        if resolved:
            base_url = resolved
    if model is None:
        return []
    catalog_path = f"{HOME_PATH}/.codex/models.json"
    # Attempt box is already isolated. Codex ACP still defaults to workspace-write
    # (bwrap) unless INITIAL_AGENT_MODE is set; keep these keys anyway.
    lines = [
        f"model = {_toml_escape(model)}",
        f"model_catalog_json = {_toml_escape(catalog_path)}",
        'sandbox_mode = "danger-full-access"',
        'approval_policy = "never"',
    ]
    if base_url and (provider or env_key):
        slug = provider or "ageval"
        lines.append(f"model_provider = {_toml_escape(slug)}")
        lines.append("")
        lines.append(f"[model_providers.{slug}]")
        lines.append(f"name = {_toml_escape(slug)}")
        lines.append(f"base_url = {_toml_escape(base_url)}")
        # Codex only speaks the Responses API (`/responses`). Chat Completions
        # gateways 404 here; set this explicitly for OpenRouter-style endpoints.
        lines.append('wire_api = "responses"')
        if env_key:
            lines.append(f"env_key = {_toml_escape(env_key)}")
    slugs: list[str] = []
    for row in rows:
        raw = _row_model_id(row)
        if raw in _SKIP_MODELS:
            continue
        _, model_id = split_model(raw)
        slug = model_id or raw
        if slug not in slugs:
            slugs.append(slug)
    return [
        OverlayFile(
            dest=".codex/models.json",
            payload={"models": [_codex_catalog_entry(slug) for slug in slugs]},
            kind="json",
        ),
        OverlayFile(
            dest=".codex/config.toml",
            payload="\n".join(lines) + "\n",
            kind="toml",
        ),
    ]


def build_claude_overlays(rows: list[Mapping[str, Any]]) -> list[OverlayFile]:
    model: str | None = None
    for row in rows:
        raw = _row_model_id(row)
        if raw in _SKIP_MODELS:
            continue
        _, model_id = split_model(raw)
        if model is None:
            model = model_id or raw
    if model is None:
        return []
    return [
        OverlayFile(
            dest=".claude/settings.json",
            payload={"model": model},
            kind="json",
        )
    ]


_BUILDERS = {
    "pi": build_pi_overlays,
    "opencode": build_opencode_overlays,
    "codex": build_codex_overlays,
    "claude-code": build_claude_overlays,
}


def overlays_for_entry(
    entry_id: str,
    job_overlay: Mapping[str, Any] | None,
) -> list[OverlayFile]:
    """Files to write for *entry_id* from the locked job. Empty if nothing to pin."""
    builder = _BUILDERS.get(entry_id)
    if builder is None:
        return []
    rows = _profiles_for_entry(job_overlay, entry_id)
    if not rows:
        return []
    if entry_id == "opencode":
        return build_opencode_overlays(rows, environment=_environment_kind(job_overlay))
    return builder(rows)
