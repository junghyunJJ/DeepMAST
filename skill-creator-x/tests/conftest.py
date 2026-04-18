"""Shared pytest helpers for skill-creator-x tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


VALID_MINIMAL_BODY = textwrap.dedent("""\
    # Test Skill

    ## Instructions
    1. Do the thing.
    2. Confirm the result.

    ## Examples
    Example 1: A basic example.

    ## Common Issues
    ### Something goes wrong
    Follow the recovery steps.
    """)


def make_skill(
    tmp_path: Path,
    *,
    folder: str = "test-skill",
    name: str | None = "test-skill",
    description: str | None = (
        "Test skill used in unit tests. Use when a test needs a synthetic skill "
        "with a clear description and required metadata fields populated."
    ),
    compatibility: str | None = None,
    license: str | None = None,
    extra_frontmatter: dict | None = None,
    body: str = VALID_MINIMAL_BODY,
    filename: str = "SKILL.md",
    include_readme: bool = False,
    references: dict[str, str] | None = None,
    scripts: dict[str, str] | None = None,
    omit_delimiters: bool = False,
) -> Path:
    """Create a synthetic skill folder under tmp_path. Returns skill dir."""
    skill_dir = tmp_path / folder
    skill_dir.mkdir(parents=True, exist_ok=True)

    fm_lines: list[str] = []
    if name is not None:
        fm_lines.append(f"name: {name}")
    if description is not None:
        fm_lines.append(f"description: {description}")
    if compatibility is not None:
        fm_lines.append(f"compatibility: {compatibility}")
    if license is not None:
        fm_lines.append(f"license: {license}")
    if extra_frontmatter:
        for key, value in extra_frontmatter.items():
            fm_lines.append(f"{key}: {value}")

    if omit_delimiters:
        content = "\n".join(fm_lines) + "\n\n" + body
    else:
        content = "---\n" + "\n".join(fm_lines) + "\n---\n\n" + body

    (skill_dir / filename).write_text(content, encoding="utf-8")

    if include_readme:
        (skill_dir / "README.md").write_text("# readme\n", encoding="utf-8")

    if references:
        (skill_dir / "references").mkdir(exist_ok=True)
        for fname, fcontent in references.items():
            (skill_dir / "references" / fname).write_text(fcontent, encoding="utf-8")

    if scripts:
        (skill_dir / "scripts").mkdir(exist_ok=True)
        for fname, fcontent in scripts.items():
            (skill_dir / "scripts" / fname).write_text(fcontent, encoding="utf-8")

    return skill_dir


@pytest.fixture
def skill_factory(tmp_path):
    """Pytest fixture returning `make_skill` bound to tmp_path."""

    def _factory(**kwargs):
        return make_skill(tmp_path, **kwargs)

    return _factory


@pytest.fixture
def fixtures_dir():
    return FIXTURES
