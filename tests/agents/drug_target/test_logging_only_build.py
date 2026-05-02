"""T7-LO: Verify the logging-only build works end-to-end.

Asserts:
- LoggingAndFallbackFilesystemBackend instantiates
- ls/glob calls flow through with original results preserved
- Each call emits exactly one structured JSONL log record
- Wrapper does NOT engage any fallback branch (T6 deferred per CP-P1-002)
"""
import json
import logging
from pathlib import Path

import pytest
from src.agents.drug_target.subagents.summarizer.fs_backend import (
    LoggingAndFallbackFilesystemBackend,
)


@pytest.fixture
def populated_root(tmp_path: Path) -> Path:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for i in range(3):
        (evidence / f"file_{i}.json").write_text("{}")
    return tmp_path


def test_ls_logs_one_record_per_call(populated_root, caplog):
    backend = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    with caplog.at_level(logging.INFO, logger="drug_target.fs_backend"):
        backend.ls("/evidence")
        backend.ls("/evidence")
    assert len(caplog.records) == 2
    payloads = [json.loads(r.message) for r in caplog.records]
    assert all(p["tool"] == "ls" for p in payloads)
    assert all(p["result_count"] == 3 for p in payloads)


def test_glob_logs_one_record_per_call(populated_root, caplog):
    backend = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    with caplog.at_level(logging.INFO, logger="drug_target.fs_backend"):
        backend.glob("*.json", path="/evidence")
    assert len(caplog.records) == 1
    p = json.loads(caplog.records[0].message)
    assert p["tool"] == "glob"
    assert p["pattern"] == "*.json"
    assert p["result_count"] == 3


def test_logging_only_build_no_fallback_branch(populated_root, caplog):
    """T6 fallback is conditional — confirm Phase 2 ships logging only."""
    backend = LoggingAndFallbackFilesystemBackend(
        root_dir=str(populated_root), virtual_mode=True
    )
    # Call ls with a path that returns empty (virtual path /no_such)
    with caplog.at_level(logging.INFO, logger="drug_target.fs_backend"):
        result = backend.ls("/no_such")
    # Native returns empty
    assert not result.entries
    # Wrapper should NOT have engaged fallback (T6 is gated on T2.5 RED).
    # Phase 2 ships logging only — confirm no fallback log line.
    payloads = [json.loads(r.message) for r in caplog.records]
    assert all("fallback_engaged" not in p for p in payloads)
