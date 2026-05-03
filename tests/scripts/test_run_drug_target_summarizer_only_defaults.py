"""Codex P2 #2 fix: argparse defaults must honor LLM_PROVIDER / LLM_MODEL env vars.

The script defines _DEFAULT_PROVIDER and _DEFAULT_MODEL at module level.
Before the fix they were hard-coded strings; after the fix they read env vars
so that `LLM_PROVIDER=ollama-openai python scripts/run_drug_target_summarizer_only.py`
automatically routes to the new provider without requiring explicit CLI flags.
"""

import importlib
import os
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable.
_SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

_MODULE_NAME = "run_drug_target_summarizer_only"


def _reload_module() -> object:
    """Force reload so module-level constants pick up the current env."""
    if _MODULE_NAME in sys.modules:
        return importlib.reload(sys.modules[_MODULE_NAME])
    return importlib.import_module(_MODULE_NAME)


def test_default_provider_honors_llm_provider_env(monkeypatch):
    """Codex P2 #2: _DEFAULT_PROVIDER must reflect LLM_PROVIDER env var at import time."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama-openai")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    mod = _reload_module()
    assert mod._DEFAULT_PROVIDER == "ollama-openai", (
        f"_DEFAULT_PROVIDER should be 'ollama-openai' when LLM_PROVIDER=ollama-openai; "
        f"got {mod._DEFAULT_PROVIDER!r}"
    )


def test_default_model_honors_llm_model_env(monkeypatch):
    """Codex P2 #2: _DEFAULT_MODEL must reflect LLM_MODEL env var at import time."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama-openai")
    monkeypatch.setenv("LLM_MODEL", "qwen3.5:35b")
    mod = _reload_module()
    assert mod._DEFAULT_MODEL == "qwen3.5:35b", (
        f"_DEFAULT_MODEL should be 'qwen3.5:35b' when LLM_MODEL=qwen3.5:35b; "
        f"got {mod._DEFAULT_MODEL!r}"
    )


def test_default_model_falls_back_to_ollama_model_env(monkeypatch):
    """Codex P2 #2: _DEFAULT_MODEL falls back to OLLAMA_MODEL when LLM_MODEL is unset."""
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:122b-custom")
    mod = _reload_module()
    assert mod._DEFAULT_MODEL == "qwen3.5:122b-custom", (
        f"_DEFAULT_MODEL should fall back to OLLAMA_MODEL; got {mod._DEFAULT_MODEL!r}"
    )


def test_default_provider_falls_back_to_ollama_when_no_env(monkeypatch):
    """Codex P2 #2: without LLM_PROVIDER env, _DEFAULT_PROVIDER remains 'ollama'."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    mod = _reload_module()
    assert mod._DEFAULT_PROVIDER == "ollama", (
        f"_DEFAULT_PROVIDER fallback should be 'ollama'; got {mod._DEFAULT_PROVIDER!r}"
    )
