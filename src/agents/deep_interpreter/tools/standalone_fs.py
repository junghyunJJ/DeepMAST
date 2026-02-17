"""Standalone filesystem tools for testing subagent graphs.

In embedded mode, DeepAgents FilesystemMiddleware auto-injects write_file/read_file
via ToolRuntime. Standalone React agents lack this infrastructure, so this module
provides lightweight replacements backed by FilesystemBackend.
"""

import os
from pathlib import Path

from deepagents.backends import FilesystemBackend
from langchain_core.tools import tool

# Singleton backend, lazy-initialized (recreated if env var changes)
_backend: FilesystemBackend | None = None
_backend_data_dir: str | None = None


def _get_backend() -> FilesystemBackend:
    global _backend, _backend_data_dir
    data_dir = os.getenv(
        "DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace"
    )
    if _backend is None or _backend_data_dir != data_dir:
        _backend = FilesystemBackend(root_dir=data_dir, virtual_mode=True)
        _backend_data_dir = data_dir
    return _backend


def _get_project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file. Virtual paths (e.g., /data_path.txt) resolve to workspace."""
    backend = _get_backend()
    if not file_path.startswith("/"):
        file_path = f"/{file_path}"
    res = backend.write(file_path, content)
    if res.error:
        return res.error
    return f"Updated file {res.path}"


@tool
def read_file(file_path: str, offset: int = 0, limit: int = 2000) -> str:
    """Read a file. Virtual paths resolve to workspace; 'skills/...' resolves to project root."""
    # Handle project-relative paths (skills/)
    if file_path.startswith("skills/"):
        project_root = _get_project_root()
        resolved = project_root / file_path
        if not resolved.exists():
            return f"Error: File '{file_path}' not found at {resolved}"
        content = resolved.read_text(encoding="utf-8")
        lines = content.splitlines()
        selected = lines[offset : offset + limit]
        return "\n".join(
            f"{i:>6}\t{line}" for i, line in enumerate(selected, start=offset + 1)
        )

    backend = _get_backend()
    if not file_path.startswith("/"):
        file_path = f"/{file_path}"
    return backend.read(file_path, offset=offset, limit=limit)
