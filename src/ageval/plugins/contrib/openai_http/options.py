"""Frozen options for the openai-http executor."""

from __future__ import annotations

from dataclasses import dataclass

from ageval.plugins.options import parse_options, stall_field


@dataclass(frozen=True, slots=True)
class OpenAIHTTPOptions:
    """Profile ``options`` for ``executor: openai-http``.

    Model fields live on the nested ``model:`` object, not here.
    """

    upstream_stall_seconds: int = stall_field()

    @classmethod
    def parse(cls, raw: object, *, location: str = "options") -> OpenAIHTTPOptions:
        return parse_options(cls, raw, location=location)


__all__ = ["OpenAIHTTPOptions"]
