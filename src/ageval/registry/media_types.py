"""Registry package / result media types (client + server shared)."""

from __future__ import annotations

DATASET_MEDIA_TYPE = "application/vnd.ageval.dataset.v1.tar+gzip"
PLUGIN_MEDIA_TYPE = "application/vnd.ageval.plugin.v1.tar+gzip"
AGENT_MEDIA_TYPE = "application/vnd.ageval.agent.v1.tar+gzip"
ATTEMPT_RESULT_MEDIA_TYPE = "application/vnd.ageval.attempt-result.v1.tar+gzip"
SUITE_RESULT_MEDIA_TYPE = "application/vnd.ageval.suite-result.v1.tar+gzip"
SHARE_SNAPSHOT_MEDIA_TYPE = "application/vnd.ageval.share-snapshot.v1.tar+gzip"
