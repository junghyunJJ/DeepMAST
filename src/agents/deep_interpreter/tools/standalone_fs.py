"""Standalone filesystem tools for testing subagent graphs.

In embedded mode, DeepAgents FilesystemMiddleware auto-injects write_file/read_file
via ToolRuntime. Standalone React agents lack this infrastructure, so this module
provides lightweight replacements backed by FilesystemBackend.
"""

import json
import os
from pathlib import Path

from deepagents.backends import FilesystemBackend
from langchain_core.tools import tool

# Singleton backend, lazy-initialized
_backend: FilesystemBackend | None = None

_DEFAULT_DATA_DIR = "/tmp/deep_interpreter_workspace"


def _get_backend() -> FilesystemBackend:
    global _backend
    current_dir = os.getenv("DEEP_INTERPRETER_DATA_DIR", _DEFAULT_DATA_DIR)
    resolved_dir = str(Path(current_dir).expanduser().resolve())
    if _backend is None or str(_backend.cwd) != resolved_dir:
        _backend = FilesystemBackend(root_dir=resolved_dir, virtual_mode=True)
    return _backend


def _get_project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def _normalize_virtual_path(file_path: str) -> str:
    """Map common container-style workspace paths into virtual FS paths."""
    if file_path == "/workspace":
        return "/"
    if file_path.startswith("/workspace/"):
        return file_path[len("/workspace") :]
    return file_path


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file. Virtual paths (e.g., /data_path.txt) resolve to workspace."""
    # Ollama may pass raw dict/list instead of JSON string
    if isinstance(content, (dict, list)):
        content = json.dumps(content, indent=2)
    file_path = _normalize_virtual_path(file_path)
    backend = _get_backend()
    if not file_path.startswith("/"):
        file_path = f"/{file_path}"
    res = backend.write(file_path, content)
    if res.error:
        return res.error
    return f"Updated file {res.path}"


@tool
def read_file(file_path: str, offset: int = 0, limit: int = 2000) -> object:
    """Read a file. Virtual paths resolve to workspace; 'skills/...' resolves to project root."""
    file_path = _normalize_virtual_path(file_path)
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
