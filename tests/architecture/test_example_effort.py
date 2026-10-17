"""Example effort lint: a pin with reasoning_options requires the top tier."""

from __future__ import annotations

from pathlib import Path

from scripts.check_example_effort import problems

_PIN = {
    "format": "ageval.model-pin/1",
    "models": {
        "zhipuai/glm-5.3": {
            "reasoning_options": [{"type": "effort", "values": ["low", "high", "max"]}],
        }
    },
    "aliases": {"glm-5.3": "zhipuai/glm-5.3"},
}


def test_under_specified_effort_fails(tmp_path: Path) -> None:
    (tmp_path / "profiles.yaml").write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                "agent_profiles:",
                "  solver:",
                "    model:",
                "      id: glm-5.3",
                "      reasoning:",
                "        effort: low",
            ]
        ),
        encoding="utf-8",
    )
    found = problems(tmp_path, _PIN)
    assert len(found) == 1
    assert "effort 'low'" in found[0]


def test_max_alias_and_missing_effort_list_pass(tmp_path: Path) -> None:
    (tmp_path / "profiles.yaml").write_text(
        "\n".join(
            [
                "agent_profiles:",
                "  solver:",
                "    model: {id: glm-5.3, reasoning: {effort: max}}",
                "  other:",
                "    model: {id: unknown-model, reasoning: {effort: low}}",
            ]
        ),
        encoding="utf-8",
    )
    assert problems(tmp_path, _PIN) == []


def test_shipped_examples_set_max_effort() -> None:
    from ageval.model.pin import load_model_pin

    root = Path(__file__).resolve().parents[2] / "examples"
    pin = load_model_pin()
    assert pin is not None
    assert problems(root, pin) == []
