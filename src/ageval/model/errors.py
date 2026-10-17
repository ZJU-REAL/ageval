"""Executor failure families.

The parent stall retries only ``TransportStall``. A wrong profile is
``ModelConfigError``. A body the client cannot decode is ``ProtocolError``.
An action the harness cannot parse is ``FormatError``. None of those three
enter the stall loop.
"""

from __future__ import annotations


class ModelConfigError(Exception):
    """Malformed or unsupported model profile. Not a stall."""

    kind: str = "model_config"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TransportStall(Exception):
    """A transport failure the parent may stall-retry."""

    def __init__(self, message: str, *, kind: str = "transport") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class ProtocolError(Exception):
    """A provider payload the client cannot decode. Not a stall."""

    def __init__(self, message: str, *, kind: str = "protocol") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class FormatError(Exception):
    """An action or tool payload the harness cannot parse. Not a stall."""

    def __init__(self, message: str, *, kind: str = "format") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


# HTTP 4xx answers that a retry can change: request timeout and rate limit.
_RETRYABLE_4XX = frozenset({408, 429})


def http_status_is_config_error(code: int) -> bool:
    """True when an upstream HTTP status means the request itself is wrong.

    Any 4xx except 408 and 429 (bad model id, bad field, auth, missing
    route) is a model config error: sending the same request again cannot
    succeed, so it must not go through upstream stall.
    """
    return 400 <= code < 500 and code not in _RETRYABLE_4XX
