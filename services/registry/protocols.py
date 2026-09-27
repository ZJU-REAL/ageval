"""Shared Protocols for Registry stores.

One narrow protocol per aggregate (package / result / org+user / inbox) plus
the token protocol. SQLite and Postgres implement the same contracts through
the shared dialect adapter; there is no god store protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from services.registry.auth.tokens import TokenInfo


@runtime_checkable
class TokenStoreProtocol(Protocol):
    def hash_token(self, raw: str) -> str: ...

    def add(
        self,
        raw_token: str,
        scopes: frozenset[str] | set[str],
        *,
        github_user: str | None = None,
    ) -> None: ...

    def auth_for(self, raw_token: str | None) -> TokenInfo: ...

    def scopes_for(self, raw_token: str | None) -> frozenset[str]: ...





