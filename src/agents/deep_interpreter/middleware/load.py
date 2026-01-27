"""Skill metadata loader for Deep Interpreter Agent.

This module provides functions for loading skill metadata from SKILL.md files
in the project skills directory. Implements Progressive Disclosure by loading
only metadata initially, allowing agents to read full skill files on demand.
"""

import re
from pathlib import Path
from typing import TypedDict

import yaml


class SkillMetadata(TypedDict):
    """Metadata extracted from a SKILL.md file.

    Attributes:
        name: Skill identifier (from YAML frontmatter or directory name)
        description: Brief description of the skill's purpose
        path: Absolute path to the SKILL.md file
        source: Origin of the skill ("project" for project-level skills)
    """

    name: str
    description: str
    path: str
    source: str


def list_skills(project_skills_dir: Path | None = None) -> list[SkillMetadata]:
    """Load skill metadata from project skills directory.

    Scans the project skills directory for subdirectories containing SKILL.md
    files and extracts metadata from their YAML frontmatter.

    Args:
        project_skills_dir: Path to the skills directory. If None, no skills loaded.

    Returns:
        List of SkillMetadata dictionaries for each valid skill found.

    Example:
        >>> skills = list_skills(Path("skills/"))
        >>> for skill in skills:
        ...     print(f"{skill['name']}: {skill['description']}")
        biomedical-literature-search: Complete workflow for CCI literature...
    """
    skills: list[SkillMetadata] = []

    if project_skills_dir is None or not project_skills_dir.exists():
        return skills

    for skill_dir in project_skills_dir.iterdir():
        if not skill_dir.is_dir():
            continue

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        metadata = _parse_skill_frontmatter(skill_file)
        if metadata:
            skills.append(
                SkillMetadata(
                    name=metadata.get("name", skill_dir.name),
                    description=metadata.get("description", ""),
                    path=str(skill_file.absolute()),
                    source="project",
                )
            )

    return skills


def _parse_skill_frontmatter(skill_file: Path) -> dict | None:
    """Parse YAML frontmatter from a SKILL.md file.

    Extracts metadata from YAML frontmatter at the beginning of the file.
    Frontmatter must be enclosed in triple dashes (---).

    Args:
        skill_file: Path to the SKILL.md file.

    Returns:
        Dictionary of parsed YAML data, or None if parsing fails.

    Example:
        Given a file with content:
            ---
            name: my-skill
            description: A helpful skill
            ---
            # Skill Content...

        Returns: {"name": "my-skill", "description": "A helpful skill"}
    """
    try:
        content = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    # Match YAML frontmatter between triple dashes
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None

    try:
        return yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None


def get_skill_content(skill_path: str | Path) -> str | None:
    """Read the full content of a skill file.

    Used when the agent decides to read a skill's full instructions
    after seeing its metadata in the system prompt.

    Args:
        skill_path: Path to the SKILL.md file.

    Returns:
        Full file content as string, or None if reading fails.
    """
    try:
        path = Path(skill_path)
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
