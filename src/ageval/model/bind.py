"""Turn a factory ``model`` argument into one ``ModelSpec``.

``None`` and the binder omit token ``entry-default`` use ``default_id``.
A string id is rejected. Flat model keys in ``options`` are rejected.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ageval.model.spec import ModelSpec, resolve_model

# Binder uses this string when the profile omitted ``model``. It is not a
# profile shape. A profile that writes the same text is rejected at lock.
OMITTED_MODEL = "entry-default"


def spec_from_factory(
    model: Any,
    options: Mapping[str, Any] | None,
    *,
    default_id: str,
) -> ModelSpec:
    """Resolve a nested model, or the executor default when the profile omitted it."""
    opts = options if isinstance(options, Mapping) else {}
    if model is None or model == OMITTED_MODEL:
        return resolve_model({"id": default_id}, opts)
    return resolve_model(model, opts)
