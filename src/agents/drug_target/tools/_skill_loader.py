"""Shared skill module loader with thread-safe caching."""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from typing import Any

SKILLS_DIR = Path(__file__).resolve().parents[4] / "skills"

_module_cache: dict[tuple[str, str], Any] = {}
_cache_lock = threading.Lock()


def load_skill_module(skill_name: str, script_name: str, module_name: str) -> Any:
    """Load a skill script as a Python module with thread-safe caching."""
    cache_key = (skill_name, script_name)
    with _cache_lock:
        if cache_key in _module_cache:
            return _module_cache[cache_key]

    script_path = SKILLS_DIR / skill_name / "scripts" / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Skill script not found: {script_path}")

    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for {script_path}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with _cache_lock:
        # Double-check: another thread may have cached it while we loaded
        if cache_key not in _module_cache:
            _module_cache[cache_key] = mod
        return _module_cache[cache_key]
