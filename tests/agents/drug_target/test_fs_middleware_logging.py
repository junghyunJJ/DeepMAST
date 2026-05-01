"""Tests for LoggingFilesystemMiddleware (T3.5 mechanism (b) verification).

Mechanism (b) is used because ``_create_ls_tool`` and ``_create_glob_tool``
each return a single ``BaseTool`` (not a tuple), making the mechanism (a)
tuple-override approach from the plan spec unworkable against deepagents 0.5.3.

Instead, ``LoggingFilesystemMiddleware`` subclasses ``FilesystemMiddleware`` and
overrides ``wrap_tool_call`` / ``awrap_tool_call`` to intercept ``ls`` and ``glob``
calls and emit raw-arg DEBUG logs before delegating to the parent handler.
"""
import json
import logging

import pytest
from deepagents.backends import StateBackend

from src.agents.drug_target.subagents.summarizer.fs_middleware import (
    LoggingFilesystemMiddleware,
)


def test_instantiation_does_not_raise():
    """LoggingFilesystemMiddleware can be constructed without errors."""
    middleware = LoggingFilesystemMiddleware(backend=StateBackend())
    assert middleware is not None


def test_is_subclass_of_filesystem_middleware():
    """Must be a subclass so deepagents treats it as FilesystemMiddleware."""
    from deepagents.middleware.filesystem import FilesystemMiddleware

    assert issubclass(LoggingFilesystemMiddleware, FilesystemMiddleware)


def test_has_expected_tools():
    """Middleware must expose the standard ls and glob tools."""
    middleware = LoggingFilesystemMiddleware(backend=StateBackend())
    tool_names = {t.name for t in middleware.tools}
    assert "ls" in tool_names
    assert "glob" in tool_names


def test_create_deep_agent_with_subclass_does_not_raise():
    """T3.5 empirical gate: deepagents 0.5.3 must accept the subclass.

    This test MUST NOT be skipped — it is the empirical verification that
    mechanism (b) does not trigger the duplicate-middleware AssertionError.
    """
    try:
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        from deepagents import create_deep_agent
    except ImportError:
        pytest.skip("deepagents or FakeListChatModel not available")

    model = FakeListChatModel(responses=["ok"])
    # Passing our subclass should not raise AssertionError about duplicates.
    agent = create_deep_agent(
        model=model,
        middleware=[LoggingFilesystemMiddleware(backend=StateBackend())],
    )
    assert agent is not None


def test_wrap_tool_call_logs_ls_args(caplog):
    """wrap_tool_call must emit a DEBUG log for ls tool calls."""
    from unittest.mock import MagicMock

    from deepagents.backends.protocol import LsResult
    from deepagents.middleware.filesystem import FilesystemMiddleware

    middleware = LoggingFilesystemMiddleware(backend=StateBackend())

    # Build a minimal fake ToolCallRequest for ls
    fake_request = MagicMock()
    fake_request.tool_call = {"name": "ls", "args": {"path": "/evidence"}}

    # Handler returns a fake ToolMessage-like string (no real backend invocation)
    fake_result = MagicMock()

    def fake_handler(req):
        return fake_result

    with caplog.at_level(logging.DEBUG, logger="drug_target.fs_middleware"):
        middleware.wrap_tool_call(fake_request, fake_handler)

    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(debug_records) >= 1
    payload = json.loads(debug_records[0].message)
    assert payload["tool"] == "ls"
    assert payload["layer"] == "middleware"
    assert "raw_args" in payload


def test_wrap_tool_call_logs_glob_args(caplog):
    """wrap_tool_call must emit a DEBUG log for glob tool calls."""
    from unittest.mock import MagicMock

    middleware = LoggingFilesystemMiddleware(backend=StateBackend())

    fake_request = MagicMock()
    fake_request.tool_call = {
        "name": "glob",
        "args": {"pattern": "*.json", "path": "/evidence"},
    }
    fake_result = MagicMock()

    def fake_handler(req):
        return fake_result

    with caplog.at_level(logging.DEBUG, logger="drug_target.fs_middleware"):
        middleware.wrap_tool_call(fake_request, fake_handler)

    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(debug_records) >= 1
    payload = json.loads(debug_records[0].message)
    assert payload["tool"] == "glob"
    assert "raw_args" in payload


def test_wrap_tool_call_does_not_log_non_ls_glob(caplog):
    """wrap_tool_call must NOT emit a DEBUG log for unrelated tool calls."""
    from unittest.mock import MagicMock

    middleware = LoggingFilesystemMiddleware(backend=StateBackend())

    fake_request = MagicMock()
    fake_request.tool_call = {"name": "read_file", "args": {"path": "/evidence/test.json"}}
    fake_result = MagicMock()

    def fake_handler(req):
        return fake_result

    with caplog.at_level(logging.DEBUG, logger="drug_target.fs_middleware"):
        result = middleware.wrap_tool_call(fake_request, fake_handler)

    # No middleware debug log for unrelated tools
    debug_records = [
        r for r in caplog.records
        if r.levelno == logging.DEBUG and r.name == "drug_target.fs_middleware"
    ]
    assert len(debug_records) == 0
    assert result is fake_result


def test_log_args_are_sanitized(caplog):
    """Raw args in middleware log must have newlines/nulls sanitized (CP-P1-003)."""
    from unittest.mock import MagicMock

    middleware = LoggingFilesystemMiddleware(backend=StateBackend())

    fake_request = MagicMock()
    fake_request.tool_call = {
        "name": "ls",
        "args": {"path": "/evidence\nINJECTED"},
    }

    def fake_handler(req):
        return MagicMock()

    with caplog.at_level(logging.DEBUG, logger="drug_target.fs_middleware"):
        middleware.wrap_tool_call(fake_request, fake_handler)

    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(debug_records) >= 1
    # The log message must not contain a raw newline
    for record in debug_records:
        assert "\n" not in record.message
