"""RED tests for .env load-order bug in scripts/run_drug_target_summarizer_only.py.

Bug (lines 46-48): os.environ.get("LLM_PROVIDER"), os.environ.get("LLM_MODEL"),
and os.environ.get("OLLAMA_MODEL") are captured BEFORE load_dotenv() runs at line 52.
As a result, values present only in .env (not shell-exported) are silently ignored
by argparse defaults — the script always falls back to hard-coded "ollama" /
"qwen3.5:122b" when those variables come only from .env.

Fix (Task #22): move load_dotenv(PROJECT_ROOT / ".env") above line 46 so that .env
is loaded into os.environ BEFORE os.environ.get() captures the defaults.

RED state expectations for scenarios (a)-(c):
  We simulate the bug by ensuring env vars are ABSENT from os.environ at module
  reload time (mimicking "only in .env, not shell-exported"), then asserting the
  GREEN expectation.  Because the bug means load_dotenv() runs too late to affect
  the already-captured module-level constants, these tests FAIL in RED state:
    args.provider == "ollama"  (hard-coded fallback, not "openai" from .env)
    args.model    == "qwen3.5:122b"  (hard-coded fallback, not "gpt-4" from .env)

Scenario (d) — shell export beats .env — PASSES in both RED and GREEN (the
override=False semantics already work correctly because shell-exported vars are
already in os.environ when load_dotenv runs).

After Task #22 moves load_dotenv() above line 46, scenarios (a)-(c) become GREEN.

Test conventions per .claude/rules/workflow/05-test.md:
  pytest, AAA, monkeypatch for env isolation, importlib.reload to re-execute
  module-level env reads, sys.argv patched to [] for argparse defaults.
  Test name format: test_<what>_<condition>_<expected>
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Module loading helpers
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

_MODULE_NAME = "run_drug_target_summarizer_only"

# Hard-coded fallback values embedded in the script (lines 62-63).
# These are the values the bug causes argparse to produce when .env is ignored.
_FALLBACK_PROVIDER = "ollama"
_FALLBACK_MODEL = "qwen3.5:122b"


def _reload_module_without_env_vars(*absent_vars: str, monkeypatch) -> object:
    """Reload the script module with specified env vars ABSENT from os.environ.

    This simulates the "value lives only in .env, not shell-exported" scenario.
    - absent_vars: env var names to remove before reload (the .env-only vars).
    - sys.argv is set to [module_name] so _parse_args() uses argparse defaults.

    In RED state (bug present): os.environ.get() at lines 46-48 sees None for
    the absent vars; load_dotenv() at line 52 would inject them, but the
    module-level constants have already captured None — too late.

    In GREEN state (fix applied): load_dotenv() runs before the os.environ.get()
    calls, so the absent vars are populated from .env in time.

    To test this without touching the real .env file, we patch load_dotenv to
    simulate what it would do: inject the .env values into os.environ at the
    right moment RELATIVE to the os.environ.get() calls.  In RED state, even
    though load_dotenv is called, it fires after the captures, so the injected
    values don't reach the constants.  We verify this by checking the argparse
    output, not the load_dotenv mock itself.
    """
    monkeypatch.setattr(sys, "argv", [_MODULE_NAME])
    for var in absent_vars:
        monkeypatch.delenv(var, raising=False)
    if _MODULE_NAME in sys.modules:
        return importlib.reload(sys.modules[_MODULE_NAME])
    return importlib.import_module(_MODULE_NAME)


# ---------------------------------------------------------------------------
# Scenario (a): LLM_PROVIDER in .env only — argparse should use "openai"
# ---------------------------------------------------------------------------


def test_parse_args_provider_dot_env_only_yields_dot_env_value(monkeypatch):
    """(a) .env has LLM_PROVIDER=openai; shell has no LLM_PROVIDER export.

    We simulate this by:
      1. Removing LLM_PROVIDER from os.environ (absent = "only in .env").
      2. Patching load_dotenv so it injects LLM_PROVIDER=openai into os.environ
         (mimicking what the real .env would do).
      3. Reloading the module.

    RED: load_dotenv() is called at line 52 — AFTER os.environ.get() at line 46
    already captured None.  The patched load_dotenv does inject the value, but
    _ENV_DEFAULT_PROVIDER was already set to None.  Result: args.provider == "ollama".
    Test FAILS because we assert "openai".

    GREEN after Task #22: load_dotenv fires before line 46, so os.environ.get()
    at line 46 sees "openai", _DEFAULT_PROVIDER = "openai", args.provider = "openai".
    """
    # Arrange — LLM_PROVIDER absent from shell env (only in .env).
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    # Simulate load_dotenv injecting LLM_PROVIDER=openai from the .env file.
    # We patch dotenv.load_dotenv so it sets the env var when called — this is
    # exactly what the real load_dotenv does.  The question is WHEN it is called
    # relative to lines 46-48.
    original_environ_get = __import__("os").environ.get

    def fake_load_dotenv(path=None, **kwargs):
        """Inject .env values as load_dotenv would — but timing is the bug."""
        import os as _os
        _os.environ.setdefault("LLM_PROVIDER", "openai")

    with patch("dotenv.load_dotenv", side_effect=fake_load_dotenv):
        mod = _reload_module_without_env_vars(
            "LLM_PROVIDER", "LLM_MODEL", "OLLAMA_MODEL", monkeypatch=monkeypatch
        )
        args = mod._parse_args()

    # Assert — after fix, args.provider must be "openai" (from .env).
    # In RED state this fails: args.provider == "ollama" (hard-coded fallback).
    assert args.provider == "openai", (
        f"args.provider should be 'openai' when .env contains LLM_PROVIDER=openai "
        f"and no shell export exists; got {args.provider!r}.\n"
        f"Bug: load_dotenv() at line 52 fires AFTER os.environ.get() at line 46 "
        f"has already captured None.  Fix: move load_dotenv() above line 46."
    )


# ---------------------------------------------------------------------------
# Scenario (b): LLM_MODEL in .env only — argparse should use "gpt-4"
# ---------------------------------------------------------------------------


def test_parse_args_model_dot_env_only_yields_dot_env_value(monkeypatch):
    """(b) .env has LLM_MODEL=gpt-4; shell has no LLM_MODEL export.

    RED: args.model == "qwen3.5:122b" (hard-coded fallback). Test FAILS.
    GREEN after Task #22: args.model == "gpt-4".
    """
    # Arrange — LLM_MODEL absent from shell env.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    def fake_load_dotenv(path=None, **kwargs):
        import os as _os
        _os.environ.setdefault("LLM_MODEL", "gpt-4")

    with patch("dotenv.load_dotenv", side_effect=fake_load_dotenv):
        mod = _reload_module_without_env_vars(
            "LLM_PROVIDER", "LLM_MODEL", "OLLAMA_MODEL", monkeypatch=monkeypatch
        )
        args = mod._parse_args()

    # Assert — after fix, args.model must be "gpt-4".
    assert args.model == "gpt-4", (
        f"args.model should be 'gpt-4' when .env contains LLM_MODEL=gpt-4 "
        f"and no shell export exists; got {args.model!r}.\n"
        f"Bug: load_dotenv() at line 52 fires AFTER os.environ.get() at line 47 "
        f"has already captured None for LLM_MODEL."
    )


# ---------------------------------------------------------------------------
# Scenario (c): OLLAMA_MODEL in .env only — argparse should use "llama3.2:1b"
# ---------------------------------------------------------------------------


def test_parse_args_ollama_model_dot_env_only_yields_dot_env_value(monkeypatch):
    """(c) .env has LLM_PROVIDER=ollama + OLLAMA_MODEL=llama3.2:1b; no shell exports.

    RED: args.model == "qwen3.5:122b" because OLLAMA_MODEL was captured as None
    at line 48 before load_dotenv ran. Test FAILS.
    GREEN after Task #22: args.model == "llama3.2:1b".
    """
    # Arrange — all three vars absent from shell env.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    def fake_load_dotenv(path=None, **kwargs):
        import os as _os
        _os.environ.setdefault("LLM_PROVIDER", "ollama")
        _os.environ.setdefault("OLLAMA_MODEL", "llama3.2:1b")

    with patch("dotenv.load_dotenv", side_effect=fake_load_dotenv):
        mod = _reload_module_without_env_vars(
            "LLM_PROVIDER", "LLM_MODEL", "OLLAMA_MODEL", monkeypatch=monkeypatch
        )
        args = mod._parse_args()

    # Assert provider (may pass even in RED because fallback is also "ollama").
    assert args.provider == "ollama", (
        f"args.provider should be 'ollama'; got {args.provider!r}"
    )
    # Assert model — this is the key failure point in RED state.
    assert args.model == "llama3.2:1b", (
        f"args.model should be 'llama3.2:1b' when .env has OLLAMA_MODEL=llama3.2:1b "
        f"and LLM_MODEL is unset; got {args.model!r}.\n"
        f"Bug: OLLAMA_MODEL captured as None at line 48 before load_dotenv."
    )


# ---------------------------------------------------------------------------
# Scenario (d): shell export takes precedence over .env (override=False semantics)
# ---------------------------------------------------------------------------


def test_parse_args_shell_export_wins_over_dot_env_llm_provider(monkeypatch):
    """(d) Shell exports LLM_PROVIDER=ollama; .env would set LLM_PROVIDER=openai.

    load_dotenv(override=False) must NOT overwrite the already-exported shell
    variable.  This tests that the fix preserves override=False semantics.

    PASSES in both RED and GREEN states:
    - RED: shell export is in os.environ at lines 46-48, so _ENV_DEFAULT_PROVIDER
      = "ollama"; load_dotenv with setdefault would not overwrite it.
    - GREEN: load_dotenv fires first but uses setdefault/"override=False", so
      the already-present "ollama" is preserved; os.environ.get() at line 46
      still returns "ollama".
    """
    # Arrange — shell export is present (simulates `export LLM_PROVIDER=ollama`).
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    # .env would set LLM_PROVIDER=openai, but override=False prevents overwrite.
    def fake_load_dotenv(path=None, **kwargs):
        import os as _os
        _os.environ.setdefault("LLM_PROVIDER", "openai")  # setdefault = override=False

    with patch("dotenv.load_dotenv", side_effect=fake_load_dotenv):
        mod = _reload_module_without_env_vars(monkeypatch=monkeypatch)
        args = mod._parse_args()

    # Assert — shell export beats .env in both RED and GREEN.
    assert args.provider == "ollama", (
        f"Shell export LLM_PROVIDER=ollama should win over .env LLM_PROVIDER=openai; "
        f"got {args.provider!r}.\n"
        f"load_dotenv(override=False) must not overwrite existing shell exports."
    )
