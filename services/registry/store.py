"""Registry row types and DTO helpers.

Unit tests: SQLite + Memory blob.
Compose / production: Postgres + S3-compatible (RustFS).

Raw API tokens are never persisted — only sha256 digests.
Visibility is only ``public`` | ``private``.
Packages require ``org_id`` on new publishes; results carry ``uploaded_by``
and optional share targets (org / user). Private read is ownership/membership
based (admin bypass); scopes alone no longer grant global private sight.

Blob stores live in ``content/blobs.py``. Schema init lives in ``db/schema.py``.
Token adapters live in ``auth/tokens.py``. Org rows and org SQL live under ``orgs/``.
"""

from __future__ import annotations

from services.registry.clock import now

# ---------------------------------------------------------------------------










