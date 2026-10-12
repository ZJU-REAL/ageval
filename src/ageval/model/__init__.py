"""Harness model contract: one ``ModelSpec`` for every executor."""

from ageval.model.errors import ModelConfigError
from ageval.model.spec import (
    API_CHAT,
    API_RESPONSES,
    API_SHORT_NAMES,
    MODEL_SPEC_FIELDS,
    ModelSpec,
    require_model_support,
    resolve_model,
)

__all__ = [
    "API_CHAT",
    "API_RESPONSES",
    "API_SHORT_NAMES",
    "MODEL_SPEC_FIELDS",
    "ModelConfigError",
    "ModelSpec",
    "require_model_support",
    "resolve_model",
]
