"""Client and server share Registry media type constants."""

from __future__ import annotations

import pytest
from services.registry import app as registry_app

from ageval.registry import results_archive
from ageval.registry.archive import MEDIA_TYPE as DATASET_MT
from ageval.registry.media_types import (
    AGENT_MEDIA_TYPE,
    ATTEMPT_RESULT_MEDIA_TYPE,
    DATASET_MEDIA_TYPE,
    PLUGIN_MEDIA_TYPE,
    SUITE_RESULT_MEDIA_TYPE,
)
from ageval.registry.plugin_package import PLUGIN_MEDIA_TYPE as PLUGIN_MT
from ageval.registry.types import ReleaseInfo


def test_media_types_aligned() -> None:
    assert DATASET_MT == DATASET_MEDIA_TYPE
    assert PLUGIN_MT == PLUGIN_MEDIA_TYPE
    assert AGENT_MEDIA_TYPE == "application/vnd.ageval.agent.v1.tar+gzip"
    assert results_archive.MEDIA_TYPE == ATTEMPT_RESULT_MEDIA_TYPE
    assert results_archive.SUITE_MEDIA_TYPE == SUITE_RESULT_MEDIA_TYPE
    assert registry_app.RESULT_MEDIA_TYPE == ATTEMPT_RESULT_MEDIA_TYPE
    assert registry_app.SUITE_RESULT_MEDIA_TYPE == SUITE_RESULT_MEDIA_TYPE


def test_package_kind_from_current_media_types_only() -> None:
    from services.registry.packages.dto import (
        package_kind_for_media_type,
    )

    assert package_kind_for_media_type(DATASET_MEDIA_TYPE) == "dataset"
    assert package_kind_for_media_type(PLUGIN_MEDIA_TYPE) == "plugin"
    assert package_kind_for_media_type(AGENT_MEDIA_TYPE) == "agent"
    with pytest.raises(ValueError, match="unknown package media_type"):
        package_kind_for_media_type("application/gzip")


def test_release_info_shape() -> None:
    info = ReleaseInfo(
        dataset_id="a/b",
        version="1.0.0",
        visibility="public",
        package_digest="sha256:" + "a" * 64,
        blob_digest="sha256:" + "b" * 64,
        size=1,
        media_type=DATASET_MEDIA_TYPE,
    )
    assert info.org_id is None
