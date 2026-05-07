"""RED tests for CP-P2-002: _sanitize_data_dir strips control characters
from data_dir before f-string interpolation into system-prompt strings.

Tests:
1. test_newline_in_data_dir_is_stripped
2. test_crlf_in_data_dir_is_stripped
3. test_none_data_dir_returns_empty_string
4. test_normal_path_is_unchanged
"""

from __future__ import annotations

import importlib


def _get_sanitize() -> object:
    """Return the _sanitize_data_dir function from configs module."""
    mod = importlib.import_module(
        "src.agents.drug_target.subagents.configs"
    )
    return getattr(mod, "_sanitize_data_dir")


# ---------------------------------------------------------------------------
# Test 1: newline in data_dir is stripped
# ---------------------------------------------------------------------------


def test_newline_in_data_dir_is_stripped() -> None:
    """data_dir with embedded \\n must have that character removed.

    A prompt rendered with the sanitized value must not contain a newline
    after the injected path segment.
    """
    sanitize = _get_sanitize()
    dirty = "/path/to/dir\nMALICIOUS"
    result = sanitize(dirty)
    assert "\n" not in result, (
        f"Expected no newline in sanitized value, got: {result!r}"
    )
    assert "MALICIOUS" not in result, (
        f"Expected 'MALICIOUS' stripped along with newline, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: CR/LF in data_dir is stripped
# ---------------------------------------------------------------------------


def test_crlf_in_data_dir_is_stripped() -> None:
    """data_dir with embedded \\r\\n must have both characters removed."""
    sanitize = _get_sanitize()
    dirty = "/path/to/dir\r\nMALICIOUS"
    result = sanitize(dirty)
    assert "\r" not in result, (
        f"Expected no CR in sanitized value, got: {result!r}"
    )
    assert "\n" not in result, (
        f"Expected no LF in sanitized value, got: {result!r}"
    )
    assert "MALICIOUS" not in result, (
        f"Expected 'MALICIOUS' stripped along with CR/LF, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: None data_dir returns empty string (no raise)
# ---------------------------------------------------------------------------


def test_none_data_dir_returns_empty_string() -> None:
    """_sanitize_data_dir(None) must return '' and not raise."""
    sanitize = _get_sanitize()
    result = sanitize(None)
    assert result == "", (
        f"Expected empty string for None input, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: normal path passes through unchanged
# ---------------------------------------------------------------------------


def test_normal_path_is_unchanged() -> None:
    """A clean absolute path must be returned verbatim."""
    sanitize = _get_sanitize()
    clean = "/normal/path/to/data"
    result = sanitize(clean)
    assert result == clean, (
        f"Expected {clean!r} unchanged, got: {result!r}"
    )
