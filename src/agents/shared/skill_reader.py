"""Skill-document reader tool (shared across agents)."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from src.agents.shared.utils import find_project_root


@tool
def read_skill_file(skill_path: str, offset: int = 0, limit: int = 2000) -> str:
    """Read a skill document from the project skills directory."""
    project_root = find_project_root()
    requested = Path(skill_path)
    if requested.is_absolute():
        resolved = requested.resolve()
    else:
        resolved = (project_root / requested).resolve()

    # Security: prevent path traversal outside project root
    if not resolved.is_relative_to(project_root):
        return f"Error: Path '{skill_path}' is outside the project directory"

    try:
        content = resolved.read_text(encoding="utf-8")
    except OSError:
        return f"Error: Skill file '{skill_path}' not found at {resolved}"

    lines = content.splitlines()
    selected = lines[offset : offset + limit]
    return "\n".join(
        f"{i:>6}\t{line}" for i, line in enumerate(selected, start=offset + 1)
    )
