"""Model configuration errors.

A ``ModelConfigError`` means the profile is wrong. Lock fails. Callers must
not treat it as a transport failure or send it through upstream stall.
"""

from __future__ import annotations

import re


class ModelConfigError(Exception):
    """Malformed or unsupported model profile. Not a stall."""

    kind: str = "model_config"

    def __init__(self, message: str) -> None:
        super().__init__(message)
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


def http_error_reason_is_config_error(reason: str) -> bool:
    """Classify an executor ``HTTPError:<code>`` reason string."""
    match = re.match(r"^(?:ModelConfigError:)?HTTPError:(\d{3})\b", reason or "")
    return bool(match) and http_status_is_config_error(int(match.group(1)))
