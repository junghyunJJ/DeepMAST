"""Standalone reproduction tests for deepagents 0.5.3 FilesystemBackend
ls/glob behavior under virtual_mode=True vs virtual_mode=False.

Plan reference: .omb/plans/2026-05-01-deepagents-filesystem-backend-ls-glob-investigation.md
- T1 (this file): RED phase — characterize empty-result combinations
- T6/T7 (future): GREEN phase — verify the wrapper fallback fixes the empty cases

API notes (deepagents 0.5.3):
  - ``backend.ls(path) -> LsResult`` with ``.entries`` (list[FileInfo] | None)
  - ``backend.glob(pattern, path) -> GlobResult`` with ``.matches`` (list[FileInfo] | None)
  - Native ``glob`` uses ``search_path.rglob(pattern)`` UNCONDITIONALLY for ALL patterns
    (filesystem.py:625) — patterns like ``*.json`` from ``path="/"`` should match
    files at any depth.
  - Native ``glob`` rejects ``..`` in patterns (filesystem.py:611-613) but NOT ``~``.
  - Native ``_resolve_path`` rejects both ``..`` and ``~`` for virtual_mode=True
    (filesystem.py:142-178).

Per CP-P2-001, the parametrize matrix is split:
  - ``*_virtual_true`` functions use VIRTUAL ABSOLUTE paths (/, /evidence, /evidence/)
  - ``*_virtual_false`` functions use RELATIVE paths only (evidence, evidence/)
because deepagents non-virtual mode resolves absolute paths against the real
filesystem root, making ``/evidence`` point at ``/evidence`` on real disk rather
than ``tmp_path/evidence`` — invalidating the control matrix.
"""
import json
from pathlib import Path

import pytest
from deepagents.backends import FilesystemBackend


# ---------------------------------------------------------------------
# Fixture: populated_root with tmp_path/evidence/hypothesis_{0..4}.json
# ---------------------------------------------------------------------
@pytest.fixture
def populated_root(tmp_path: Path) -> Path:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for i in range(5):
        (evidence / f"hypothesis_{i}.json").write_text(json.dumps({"i": i}))
    return tmp_path


# =====================================================================
# virtual_mode=True matrix — virtual absolute paths
# =====================================================================

@pytest.mark.parametrize("start,pattern", [
    ("/", "*.json"),                  # broad root + simple pattern (relies on rglob)
    ("/", "evidence/*.json"),         # root + scoped pattern
    ("/", "**/*.json"),               # root + recursive pattern
    ("/evidence", "*.json"),
    ("/evidence/", "*.json"),
])
def test_glob_finds_files_virtual_true(populated_root, start, pattern):
    """glob() should return the 5 JSON files for all virtual-path combinations."""
    backend = FilesystemBackend(root_dir=str(populated_root), virtual_mode=True)
    result = backend.glob(pattern, path=start)
    assert result.matches, (
        f"glob({pattern!r}, path={start!r}, virtual_mode=True) returned empty; "
        f"populated_root has 5 files. matches={result.matches!r}, error={result.error!r}"
    )


@pytest.mark.parametrize("start", [
    "/",
    "/evidence",
    "/evidence/",
])
def test_ls_finds_files_virtual_true(populated_root, start):
    """ls() should return non-empty listing for all virtual-path combinations."""
    backend = FilesystemBackend(root_dir=str(populated_root), virtual_mode=True)
    result = backend.ls(start)
    assert result.entries, (
        f"ls({start!r}, virtual_mode=True) returned empty; "
        f"populated_root has 5 files. entries={result.entries!r}, error={result.error!r}"
    )


# =====================================================================
# virtual_mode=False control matrix — RELATIVE paths only
# =====================================================================
# Per CP-P2-001: in non-virtual mode, an absolute path like "/evidence"
# resolves against the real filesystem root (e.g., /evidence on disk),
# NOT under tmp_path. So the control matrix uses relative paths only.

@pytest.mark.parametrize("start,pattern", [
    ("evidence", "*.json"),
    ("evidence/", "*.json"),
    ("evidence", "**/*.json"),
])
def test_glob_finds_files_virtual_false(populated_root, start, pattern):
    """glob() should return 5 JSON files for relative-path combinations under non-virtual mode."""
    backend = FilesystemBackend(root_dir=str(populated_root), virtual_mode=False)
    result = backend.glob(pattern, path=start)
    assert result.matches, (
        f"glob({pattern!r}, path={start!r}, virtual_mode=False) returned empty; "
        f"populated_root has 5 files. matches={result.matches!r}, error={result.error!r}"
    )


@pytest.mark.parametrize("start", [
    "evidence",
    "evidence/",
])
def test_ls_finds_files_virtual_false(populated_root, start):
    """ls() should return non-empty listing for relative-path combinations under non-virtual mode."""
    backend = FilesystemBackend(root_dir=str(populated_root), virtual_mode=False)
    result = backend.ls(start)
    assert result.entries, (
        f"ls({start!r}, virtual_mode=False) returned empty; "
        f"populated_root has 5 files. entries={result.entries!r}, error={result.error!r}"
    )


# =====================================================================
# Negative tests — traversal patterns MUST raise ValueError (native behavior)
# =====================================================================
# These run on the native FilesystemBackend (not the wrapper, which doesn't
# exist yet). Native rejects:
#   - ``..`` in glob patterns (filesystem.py:611-613)
#   - ``..`` and ``~`` in path arguments via _resolve_path (filesystem.py:142-178)
# Native does NOT reject ``~`` in glob patterns — only ``..``. The wrapper (T6,
# future) will add ``~`` rejection per CP-P1-004.

@pytest.mark.parametrize("pattern", ["../etc/*.json"])
def test_glob_blocks_dotdot_in_pattern(populated_root, pattern):
    """Native glob() rejects ``..`` in patterns (security guard)."""
    backend = FilesystemBackend(root_dir=str(populated_root), virtual_mode=True)
    with pytest.raises(ValueError, match="(traversal|outside)"):
        backend.glob(pattern, path="/")


def test_ls_blocks_dotdot_path(populated_root):
    """Native ls() via _resolve_path rejects ``..`` in paths."""
    backend = FilesystemBackend(root_dir=str(populated_root), virtual_mode=True)
    with pytest.raises(ValueError, match="(traversal|outside)"):
        backend.ls("../")


@pytest.mark.xfail(
    reason=(
        "deepagents 0.5.3 _resolve_path prepends '/' to non-absolute paths BEFORE "
        "checking startswith('~'), so ls('~/secrets') becomes vpath='/~/secrets' "
        "which startswith('~') does NOT match — the upstream guard is bypassed. "
        "Only the middleware-layer validate_path(utils.py:427) correctly rejects "
        "'~/secrets'. Documented gap; the wrapper-side _path_has_forbidden_token "
        "(planned T6, currently SKIPPED per CP-P1-002 conditional shipping) will "
        "close this when shipped."
    ),
    strict=True,
)
def test_ls_blocks_tilde_path_xfail_documented_upstream_gap(populated_root):
    """xfail: documents that native ls('~/secrets') does NOT raise on 0.5.3."""
    backend = FilesystemBackend(root_dir=str(populated_root), virtual_mode=True)
    with pytest.raises(ValueError, match="(traversal|outside)"):
        backend.ls("~/secrets")
