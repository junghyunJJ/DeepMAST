"""Shared utility functions for agent modules."""

from pathlib import Path


def find_project_root() -> Path:
    """Find project root by searching parent directories for pyproject.toml or .git.

    Raises:
        FileNotFoundError: If no project root marker is found.
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    raise FileNotFoundError(
        f"Could not find project root from {current}. "
        "Ensure pyproject.toml or .git exists in a parent directory."
    )
