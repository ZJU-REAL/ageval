"""Harness model contract: one ``ModelSpec`` for every executor."""

from ageval.model.bind import OMITTED_MODEL, spec_from_factory
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
    "OMITTED_MODEL",
    "ModelConfigError",
    "ModelSpec",
    "require_model_support",
    "resolve_model",
    "spec_from_factory",
]
