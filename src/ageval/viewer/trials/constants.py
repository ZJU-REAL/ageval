"""Viewer trial preview / enumeration caps and text suffixes."""

from __future__ import annotations

# Preview / enumeration caps (operator-facing local tool, not bulk export).
MAX_FILE_BYTES = 512 * 1024
MAX_TREE_ENTRIES = 800
MAX_TRAJECTORY_STEPS = 2_000
MAX_JSONL_LINE = 256 * 1024

TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".txt",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".py",
    ".sh",
    ".log",
    ".csv",
    ".tsv",
    ".xml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".ini",
    ".cfg",
    ".conf",
}

# Templates are not secrets. Real env files stay redacted.
_ENV_EXAMPLE_SUFFIXES = (".example", ".sample", ".template", ".dist")


def is_env_example(name: str) -> bool:
    lowered = name.lower()
    return "env" in lowered and lowered.endswith(_ENV_EXAMPLE_SUFFIXES)


def is_secret_basename(name: str) -> bool:
    lowered = name.lower()
    if is_env_example(lowered):
        return False
    return lowered in {".env", ".env.local", ".env.production"} or lowered.startswith(".env.")


def is_preview_text(name: str, suffix: str, mime: str) -> bool:
    if is_env_example(name):
        return True
    return (
        suffix in TEXT_SUFFIXES
        or mime.startswith("text/")
        or mime in {"application/json", "application/xml", "application/x-yaml"}
    )
