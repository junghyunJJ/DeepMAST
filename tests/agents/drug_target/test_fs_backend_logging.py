"""Tests for LoggingAndFallbackFilesystemBackend (T3 — logging only)."""
import json
from pathlib import Path

import pytest
from src.agents.drug_target.subagents.summarizer.fs_backend import (
    LoggingAndFallbackFilesystemBackend,
    _sanitize_for_log,
)


@pytest.fixture
def populated_root(tmp_path: Path) -> Path:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for i in range(3):
        (evidence / f"hypothesis_{i}.json").write_text("{}")
    return tmp_path


def test_sanitize_strips_newlines():
    s = "/evidence\nINJECTED:line"
    out = _sanitize_for_log(s)
    assert "\n" not in out
    assert "\\n" in out


def test_sanitize_strips_carriage_returns_and_null():
    assert "\r" not in _sanitize_for_log("/evidence\r")
    assert "\x00" not in _sanitize_for_log("/evidence\x00")


def test_sanitize_truncates_long_input():
    long = "x" * 700
    out = _sanitize_for_log(long)
    assert "TRUNCATED" in out
    assert len(out) < 700


def test_ls_emits_structured_log(populated_root, caplog):
    backend = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    with caplog.at_level("INFO", logger="drug_target.fs_backend"):
        result = backend.ls("/evidence")
    assert result.entries  # original behavior preserved
    assert len(caplog.records) == 1
    payload = json.loads(caplog.records[0].message)
    assert payload["tool"] == "ls"
    assert payload["path"] == "/evidence"
    assert payload["result_count"] == 3


def test_glob_emits_structured_log(populated_root, caplog):
    backend = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    with caplog.at_level("INFO", logger="drug_target.fs_backend"):
        result = backend.glob("*.json", path="/evidence")
    assert result.matches
    payload = json.loads(caplog.records[0].message)
    assert payload["tool"] == "glob"
    assert payload["pattern"] == "*.json"
    assert payload["result_count"] == 3


def test_log_payload_strips_path_newlines(populated_root, caplog):
    """CP-P1-003: log injection prevention."""
    backend = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    # Use a path that might be accepted or rejected; we want sanitization to run.
    # The injected newline should never appear as a raw newline in any log record.
    injected = "/evidence/normal\nFAKE INJECTED"
    with caplog.at_level("INFO", logger="drug_target.fs_backend"):
        try:
            backend.ls(injected)
        except (ValueError, OSError):
            pass
    # Any log records that exist must not contain a raw newline in the message
    for record in caplog.records:
        assert "\n" not in record.message  # the message itself is one line


def test_ls_log_contains_timestamp(populated_root, caplog):
    backend = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    with caplog.at_level("INFO", logger="drug_target.fs_backend"):
        backend.ls("/evidence")
    payload = json.loads(caplog.records[0].message)
    assert "timestamp" in payload
    assert isinstance(payload["timestamp"], float)


def test_glob_log_contains_timestamp(populated_root, caplog):
    backend = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    with caplog.at_level("INFO", logger="drug_target.fs_backend"):
        backend.glob("*.json", path="/evidence")
    payload = json.loads(caplog.records[0].message)
    assert "timestamp" in payload
    assert isinstance(payload["timestamp"], float)


def test_ls_returns_original_result_unchanged(populated_root):
    """Logging must not alter the returned LsResult."""
    from deepagents.backends import FilesystemBackend

    native = FilesystemBackend(root_dir=str(populated_root), virtual_mode=True)
    logging_backend = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    native_result = native.ls("/evidence")
    logging_result = logging_backend.ls("/evidence")
    assert logging_result.entries == native_result.entries
    assert logging_result.error == native_result.error


def test_glob_returns_original_result_unchanged(populated_root):
    """Logging must not alter the returned GlobResult."""
    from deepagents.backends import FilesystemBackend

    native = FilesystemBackend(root_dir=str(populated_root), virtual_mode=True)
    logging_backend = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    native_result = native.glob("*.json", path="/evidence")
    logging_result = logging_backend.glob("*.json", path="/evidence")
    assert logging_result.matches == native_result.matches
    assert logging_result.error == native_result.error
