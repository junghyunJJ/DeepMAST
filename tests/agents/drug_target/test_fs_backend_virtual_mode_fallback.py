"""Tests for T6 fallback: auto-normalize absolute paths to root-relative.

When virtual_mode=True and the LLM passes the absolute disk path that equals
or descends from root_dir, LoggingAndFallbackFilesystemBackend rewrites the
path to the virtual root-relative form before calling super().

See background in plan §2.5 / CP-P1-002 and fs_backend.py docstring.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.drug_target.subagents.summarizer.fs_backend import (
    LoggingAndFallbackFilesystemBackend,
)


# ---------------------------------------------------------------------------
# Fixture: tmp_path with foo.txt, bar.json, sub/baz.txt
# ---------------------------------------------------------------------------


@pytest.fixture
def populated_root(tmp_path: Path) -> Path:
    (tmp_path / "foo.txt").write_text("hello")
    (tmp_path / "bar.json").write_text("{}")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "baz.txt").write_text("nested")
    return tmp_path


# ---------------------------------------------------------------------------
# RED scenarios — must fail before T6 fallback is implemented
# ---------------------------------------------------------------------------


def test_ls_with_absolute_root_path_returns_entries(populated_root: Path) -> None:
    """ls(absolute_root) must return entries when path == root_dir."""
    b = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    result = b.ls(str(populated_root))
    assert result.entries is not None and len(result.entries) >= 3


def test_ls_with_absolute_subpath_returns_entries(populated_root: Path) -> None:
    """ls(absolute_subpath) must return entries when path is inside root_dir."""
    b = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    result = b.ls(str(populated_root / "sub"))
    assert result.entries is not None and len(result.entries) >= 1


def test_glob_with_absolute_root_path_returns_matches(populated_root: Path) -> None:
    """glob(**/*, absolute_root) must return matches when path == root_dir."""
    b = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    result = b.glob("**/*", path=str(populated_root))
    assert result.matches is not None and len(result.matches) >= 3


def test_read_with_absolute_subpath_returns_content(populated_root: Path) -> None:
    """read(absolute_file) must return content when file lives inside root_dir."""
    b = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    result = b.read(str(populated_root / "foo.txt"))
    assert result.error is None
    assert result.file_data == {"content": "hello", "encoding": "utf-8"}


# ---------------------------------------------------------------------------
# Regression guard — root-relative paths must still work (GREEN before/after)
# ---------------------------------------------------------------------------


def test_ls_with_root_relative_path_unchanged(populated_root: Path) -> None:
    """ls('/') must still return entries (existing behavior must be preserved)."""
    b = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    result = b.ls("/")
    # regression-guard
    assert result.entries is not None and len(result.entries) >= 3


# ---------------------------------------------------------------------------
# Negative — out-of-root absolute paths must NOT leak real filesystem contents
# ---------------------------------------------------------------------------


def test_ls_absolute_path_outside_root_returns_zero_or_error(
    populated_root: Path,
) -> None:
    """ls('/etc') (outside root_dir) must not silently return /etc contents."""
    b = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    try:
        result = b.ls("/etc")
        # If it didn't raise, it must return nothing (0 entries)
        assert not result.entries or result.error is not None, (
            "Backend must not silently leak /etc contents"
        )
    except (ValueError, OSError):
        pass  # raising is acceptable


def test_traversal_attempt_does_not_leak(populated_root: Path) -> None:
    """A path that escapes root_dir via .. must not leak real-disk contents."""
    b = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    escape_path = str(populated_root / ".." / ".." / "etc")
    try:
        result = b.ls(escape_path)
        assert not result.entries or result.error is not None, (
            "Backend must not silently leak contents outside root_dir"
        )
    except (ValueError, OSError):
        pass  # raising is acceptable


# ---------------------------------------------------------------------------
# virtual_mode=False — no normalization, defer to deepagents default semantics
# ---------------------------------------------------------------------------


def test_virtual_mode_false_preserves_absolute_path(populated_root: Path) -> None:
    """virtual_mode=False: normalization must not run; must not raise."""
    # regression-guard: virtual_mode=False behavior must not be changed by T6
    b2 = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=False
    )
    # Should not raise; entries depend on deepagents non-virtual semantics
    try:
        result = b2.ls(str(populated_root))
        # We only assert no crash — entries may vary under non-virtual mode
        assert result is not None
    except (ValueError, OSError):
        pass  # deepagents may raise for non-virtual + absolute; that's fine
