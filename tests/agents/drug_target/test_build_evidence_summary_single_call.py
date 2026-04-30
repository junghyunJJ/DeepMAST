"""Phase 2 RED test — BuildEvidenceSummaryGuardMiddleware.

Asserts:
1. The second build_evidence_summary call in a single agent run returns a
   ToolMessage whose content (JSON-decoded) contains "already_invoked".
2. The underlying tool function is invoked exactly once per agent run.
3. Middleware state resets between independent agent runs (second run is clean).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, call

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command


# ---------------------------------------------------------------------------
# Helpers — minimal ToolCallRequest stub
# ---------------------------------------------------------------------------


def _make_request(tool_name: str, tool_id: str = "call_001") -> Any:
    """Return a minimal ToolCallRequest-like object with .tool_call dict."""

    class _FakeRequest:
        tool_call = {"name": tool_name, "id": tool_id, "args": {}}

    return _FakeRequest()


def _make_build_evidence_request(tool_id: str = "call_bes_001") -> Any:
    return _make_request("build_evidence_summary", tool_id)


# ---------------------------------------------------------------------------
# T6a: second call blocked, content contains "already_invoked"
# ---------------------------------------------------------------------------


def test_second_build_evidence_summary_returns_blocked_tool_message() -> None:
    """Second invocation of build_evidence_summary must return a blocked ToolMessage."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        BuildEvidenceSummaryGuardMiddleware,
    )

    middleware = BuildEvidenceSummaryGuardMiddleware()

    real_tool_mock = MagicMock(return_value=ToolMessage(
        content="evidence summary built", tool_call_id="call_bes_001"
    ))

    # First call — should pass through to handler
    req1 = _make_build_evidence_request("call_bes_001")
    result1 = middleware.wrap_tool_call(req1, real_tool_mock)
    assert real_tool_mock.call_count == 1, "handler must be called on first invocation"

    # Second call in same run — must be blocked
    req2 = _make_build_evidence_request("call_bes_002")
    result2 = middleware.wrap_tool_call(req2, real_tool_mock)
    assert real_tool_mock.call_count == 1, (
        "handler must NOT be called on second invocation; "
        f"call_count={real_tool_mock.call_count}"
    )

    assert isinstance(result2, ToolMessage), (
        f"second call must return ToolMessage, got {type(result2)}"
    )
    assert result2.tool_call_id == "call_bes_002", (
        f"tool_call_id must match request id, got {result2.tool_call_id}"
    )

    import json
    payload = json.loads(result2.content)
    assert "already_invoked" in payload, (
        f"blocked content must contain 'already_invoked' key; got {payload}"
    )


# ---------------------------------------------------------------------------
# T6b: non-build_evidence_summary calls pass through unaffected
# ---------------------------------------------------------------------------


def test_other_tool_calls_pass_through() -> None:
    """Non-build_evidence_summary tools must always pass through."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        BuildEvidenceSummaryGuardMiddleware,
    )

    middleware = BuildEvidenceSummaryGuardMiddleware()
    handler = MagicMock(return_value=ToolMessage(content="ok", tool_call_id="call_x"))

    req = _make_request("ls", "call_x")
    result = middleware.wrap_tool_call(req, handler)

    assert handler.call_count == 1
    assert isinstance(result, ToolMessage)
    assert result.content == "ok"


# ---------------------------------------------------------------------------
# T6c: state resets between independent middleware instances (separate runs)
# ---------------------------------------------------------------------------


def test_middleware_state_resets_on_new_instance() -> None:
    """A new middleware instance must allow a fresh build_evidence_summary call."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        BuildEvidenceSummaryGuardMiddleware,
    )

    import json

    # First run — exhaust the guard
    mw1 = BuildEvidenceSummaryGuardMiddleware()
    handler1 = MagicMock(return_value=ToolMessage(content="done", tool_call_id="c1"))
    mw1.wrap_tool_call(_make_build_evidence_request("c1"), handler1)  # allowed
    result_blocked = mw1.wrap_tool_call(_make_build_evidence_request("c2"), handler1)
    assert json.loads(result_blocked.content).get("already_invoked") is True

    # Second run — fresh instance must allow the call
    mw2 = BuildEvidenceSummaryGuardMiddleware()
    handler2 = MagicMock(return_value=ToolMessage(content="done2", tool_call_id="c3"))
    result_allowed = mw2.wrap_tool_call(_make_build_evidence_request("c3"), handler2)
    assert handler2.call_count == 1, (
        "fresh middleware instance must allow first build_evidence_summary call"
    )
    assert isinstance(result_allowed, ToolMessage)
    assert result_allowed.content == "done2"


# ---------------------------------------------------------------------------
# T6d: async wrap_tool_call also blocks on second call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_second_build_evidence_summary_blocked() -> None:
    """awrap_tool_call must also block the second build_evidence_summary call."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        BuildEvidenceSummaryGuardMiddleware,
    )
    import json

    middleware = BuildEvidenceSummaryGuardMiddleware()

    async def async_handler(req: Any) -> ToolMessage:
        return ToolMessage(content="built", tool_call_id=req.tool_call["id"])

    # First call
    req1 = _make_build_evidence_request("async_c1")
    result1 = await middleware.awrap_tool_call(req1, async_handler)
    assert result1.content == "built"

    # Second call — blocked
    req2 = _make_build_evidence_request("async_c2")
    result2 = await middleware.awrap_tool_call(req2, async_handler)
    assert isinstance(result2, ToolMessage)
    payload = json.loads(result2.content)
    assert "already_invoked" in payload
