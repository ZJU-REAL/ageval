"""Which recorded commands must be replayed outside the checkpoint trees."""

from __future__ import annotations

import re

# Package managers that change the image outside workspace, home, and artifacts.
_PACKAGE_MANAGER = re.compile(
    r"(?:^|&&|\|\||;)\s*(?:sudo\s+)?(?:apt-get|apk|dnf|yum)\b"
    r"|(?:^|&&|\|\||;)\s*(?:sudo\s+)?pip3?\s+install\b"
    r"|(?:^|&&|\|\||;)\s*(?:sudo\s+)?npm\s+install\s+-g\b"
)


def command_system_effect(command: str, cwd: str | None = None) -> bool:
    """True when a command's effect is outside the checkpointed attempt trees."""
    if isinstance(cwd, str) and cwd.strip() and not _inside_attempt(cwd.strip()):
        return True
    return _PACKAGE_MANAGER.search(command.strip()) is not None


def _inside_attempt(cwd: str) -> bool:
    path = cwd.rstrip("/") or "/"
    return path == "/attempt" or path.startswith("/attempt/")
