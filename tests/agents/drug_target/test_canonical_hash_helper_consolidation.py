"""Tests: _canonical_payload_hash deleted; HypothesisRetryLoopMiddleware uses canonical_json_hash."""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MIDDLEWARE_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "src/agents/drug_target/subagents/summarizer/middleware.py"
)


def _middleware_source() -> str:
    return _MIDDLEWARE_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: _canonical_payload_hash must not exist in the module
# ---------------------------------------------------------------------------


def test_canonical_payload_hash_deleted_from_middleware():
    """_canonical_payload_hash must be absent from the middleware module."""
    # Import via the normal package path so the module is registered in
    # sys.modules. The previous spec_from_file_location pattern crashed
    # under Python 3.12 because `@dataclass` + `from __future__ import
    # annotations` requires sys.modules[cls.__module__] to be present
    # when the decorator processes string-form annotations.
    mod = importlib.import_module(
        "src.agents.drug_target.subagents.summarizer.middleware"
    )
    assert not hasattr(mod, "_canonical_payload_hash"), (
        "_canonical_payload_hash still exists on the middleware module — it must be deleted"
    )

    # Also verify at the source level: no string occurrence in file
    source = _middleware_source()
    assert "_canonical_payload_hash" not in source, (
        "_canonical_payload_hash string still found in middleware.py source"
    )


# ---------------------------------------------------------------------------
# Test 2: canonical_json_hash from report_expansion_schema is imported & used
# ---------------------------------------------------------------------------


def test_hypothesis_retry_loop_uses_report_expansion_canonical_json_hash():
    """HypothesisRetryLoopMiddleware must import and call canonical_json_hash."""
    source = _middleware_source()

    # 1. The import must be present in the source text
    assert "canonical_json_hash" in source, (
        "canonical_json_hash is not imported/referenced in middleware.py"
    )
    assert "report_expansion_schema" in source, (
        "report_expansion_schema import not found in middleware.py"
    )

    # 2. Use AST to confirm canonical_json_hash is called inside the class body
    tree = ast.parse(source)
    call_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                call_names.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                call_names.append(node.func.attr)
    assert "canonical_json_hash" in call_names, (
        "canonical_json_hash is not called anywhere in middleware.py"
    )


# ---------------------------------------------------------------------------
# Test 3: Functional — HypothesisRetryLoopMiddleware blocks identical hashes
#          using canonical_json_hash (behaviour must be preserved post-switch)
# ---------------------------------------------------------------------------


def test_hypothesis_retry_loop_blocks_identical_payload_after_rejection():
    """After a rejection, identical payloads are blocked (behaviour unchanged)."""
    from langchain_core.messages import ToolMessage

    from src.agents.drug_target.subagents.summarizer.middleware import (
        HypothesisRetryLoopMiddleware,
    )

    middleware = HypothesisRetryLoopMiddleware()

    request = MagicMock()
    request.tool_call = {
        "name": "save_hypothesis_report",
        "args": {"report": {"title": "Test", "body": "Hello"}},
        "id": "call_1",
    }

    # First call: handler returns a rejection
    rejected_msg = ToolMessage(
        content=json.dumps({"saved": False, "error": "duplicate"}),
        tool_call_id="call_1",
    )

    def handler_reject(req):
        return rejected_msg

    result1 = middleware.wrap_tool_call(request, handler_reject)
    assert isinstance(result1, ToolMessage)

    # Second call with identical payload: must be blocked without calling handler
    handler_called = []

    def handler_must_not_be_called(req):
        handler_called.append(True)
        return ToolMessage(content=json.dumps({"saved": True}), tool_call_id="call_1")

    result2 = middleware.wrap_tool_call(request, handler_must_not_be_called)
    assert not handler_called, "handler was called on blocked retry — middleware failed"
    content = json.loads(str(result2.content))
    assert content["saved"] is False
    assert "payload_hash" in content


# ---------------------------------------------------------------------------
# Test 4: Different payload must NOT be blocked
# ---------------------------------------------------------------------------


def test_hypothesis_retry_loop_passes_different_payload():
    """A mutated payload must not be blocked even after a prior rejection."""
    from langchain_core.messages import ToolMessage

    from src.agents.drug_target.subagents.summarizer.middleware import (
        HypothesisRetryLoopMiddleware,
    )

    middleware = HypothesisRetryLoopMiddleware()

    def make_request(payload: dict):
        req = MagicMock()
        req.tool_call = {
            "name": "save_hypothesis_report",
            "args": {"report": payload},
            "id": "call_x",
        }
        return req

    rejected_msg = ToolMessage(
        content=json.dumps({"saved": False, "error": "dup"}),
        tool_call_id="call_x",
    )
    middleware.wrap_tool_call(make_request({"title": "v1"}), lambda r: rejected_msg)

    # Different payload — must pass through to handler
    handler_called = []

    def handler_ok(req):
        handler_called.append(True)
        return ToolMessage(
            content=json.dumps({"saved": True}), tool_call_id="call_x"
        )

    middleware.wrap_tool_call(make_request({"title": "v2"}), handler_ok)
    assert handler_called, "mutated payload was incorrectly blocked"
