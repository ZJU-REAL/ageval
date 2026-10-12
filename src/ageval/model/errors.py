"""Model configuration errors.

A ``ModelConfigError`` means the profile is wrong. Lock fails. Callers must
not treat it as a transport failure or send it through upstream stall.
"""

from __future__ import annotations


class ModelConfigError(Exception):
    """Malformed or unsupported model profile. Not a stall."""

    kind: str = "model_config"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
