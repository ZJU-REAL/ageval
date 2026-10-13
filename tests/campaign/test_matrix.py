"""Campaign matrix expansion tests."""

from __future__ import annotations

import pytest

from ageval.application.campaign import MatrixAxis, expand_matrix, parse_matrix_arg
from ageval.config.errors import ConfigError


def test_expand_cartesian() -> None:
    axes = [
        MatrixAxis("/parameters/a", (1, 2)),
        MatrixAxis("/parameters/b", ("x",)),
    ]
    variants = expand_matrix(axes)
    assert len(variants) == 2
    assert variants[0]["/parameters/a"] == 1


def test_unsupported_pointer() -> None:
    with pytest.raises(ConfigError) as ei:
        parse_matrix_arg('/provider/kind=["docker"]')
    assert ei.value.error_code == "campaign_matrix_pointer_unsupported"


def test_parse_ok() -> None:
    axis = parse_matrix_arg("/parameters/seed=[1,2,3]")
    assert axis.values == (1, 2, 3)


def test_parse_profile_axis() -> None:
    axis = parse_matrix_arg('/agent_profiles/solver/model/id=["a","b"]')
    assert axis.pointer == "/agent_profiles/solver/model/id"
    assert axis.values == ("a", "b")
