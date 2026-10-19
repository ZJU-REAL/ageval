"""Skills layout: proper skill packages + discovery symlink + shipped CLI only."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / "skills"
AGENTS_SKILLS = REPO / ".agents" / "skills"

EXPECTED = (
    "ageval-platform",
    "ageval-cli",
    "ageval-config-package",
    "ageval-sdk-harness",
)


def _frontmatter(text: str) -> str:
    assert text.startswith("---\n"), "missing frontmatter start"
    end = text.index("\n---\n", 4)
    return text[4:end]


def test_agents_skills_symlink_resolves() -> None:
    assert AGENTS_SKILLS.is_symlink() or AGENTS_SKILLS.resolve() == SKILLS.resolve()
    assert AGENTS_SKILLS.resolve() == SKILLS.resolve()
    for name in EXPECTED:
        assert (AGENTS_SKILLS / name / "SKILL.md").is_file(), name


def test_four_skills_are_proper_packages() -> None:
    for name in EXPECTED:
        skill_dir = SKILLS / name
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.is_file(), skill_dir
        text = skill_md.read_text(encoding="utf-8")
        fm = _frontmatter(text)
        m = re.search(r"^name:\s*(\S+)\s*$", fm, re.M)
        assert m, f"name missing in {name}"
        assert m.group(1) == name
        assert re.search(r"^description:\s*", fm, re.M), name
        # description should carry when-to-use triggers (loaded always)
        desc = fm.split("description:", 1)[1]
        assert (
            "Use when" in desc
            or "when" in desc.lower()
            or "Triggers" in desc
            or "triggers" in desc.lower()
        )
        assert (skill_dir / "agents" / "openai.yaml").is_file(), name
        # progressive disclosure: at least one reference file
        refs = (
            list((skill_dir / "references").glob("*.md"))
            if (skill_dir / "references").is_dir()
            else []
        )
        assert refs, f"{name} should have references/"


def test_cli_skill_commands_exist_in_production_cli() -> None:
    skill = (SKILLS / "ageval-cli" / "SKILL.md").read_text(encoding="utf-8")
    cli_dir = REPO / "src" / "ageval" / "cli"
    sources = "\n".join(p.read_text(encoding="utf-8") for p in cli_dir.glob("*.py"))
    claimed = set(re.findall(r"`ageval (lock|run|campaign|evidence|status|submit|cancel)\b", skill))
    assert claimed, "cli skill must document ageval commands"
    for cmd in claimed:
        assert f'@app.command("{cmd}")' in sources, cmd


def test_platform_red_lines_forbid_inferring_pass() -> None:
    refs = (SKILLS / "ageval-platform" / "references" / "red-lines.md").read_text(encoding="utf-8")
    assert "Infer `PASS`" in refs
    assert "RunTerminal.completed" in refs


def test_no_skill_folder_readme_clutter() -> None:
    """skill-creator: skill packages must not ship auxiliary README.md."""
    for name in EXPECTED:
        assert not (SKILLS / name / "README.md").exists()
