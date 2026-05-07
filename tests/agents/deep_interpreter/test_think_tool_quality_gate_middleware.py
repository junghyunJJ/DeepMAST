"""RED tests for ThinkToolQualityGateMiddleware (Task #3 — Phase 2 RED).

These tests define the full behavioral contract that Task #4 (GREEN) must
implement.  They MUST all fail at import time (ImportError) until the module
``src/agents/deep_interpreter/middleware/think_tool_quality_gate.py`` is
created.

-------------------------------------------------------------------
CONTRACT (read by GREEN implementor)
-------------------------------------------------------------------

Class: ThinkToolQualityGateMiddleware(AgentMiddleware)

Constructor args:
    min_score: float  — default 0.7, overridden by THINK_TOOL_MIN_SCORE env var
    max_retries: int  — default 2, overridden by THINK_TOOL_MAX_RETRIES env var

The middleware intercepts ``think_tool`` calls via ``wrap_tool_call``.
It reads the handler-returned ToolMessage whose ``content`` is a JSON blob
with the shape produced by ``src/agents/deep_interpreter/tools/think.py``:

    {
        "success": bool,
        "result": str | None,   # full reflection text from MCP server
        "parsed_score": float | None,
        "should_continue": bool,
        ...
    }

After the handler returns, the middleware evaluates:

D2: score gate  — parsed_score < min_score → retry
D3: retry cap   — if retry_count >= max_retries → BLOCKED (not retry)
D4: None-score  — parsed_score is None → strict fail / retry (not advisory)
D5: clamp       — any ``score_threshold`` in request args is IGNORED; server
                   min_score is always applied.
R2: reflection content must contain EITHER
        (i)  at least one filename pattern: r"[a-z0-9_]+\\.json"
        OR (ii) at least one numeric pattern: r"\\d+(\\.\\d+)?"
      Absence of both → retry (even when score passes D2).

Returned ToolMessage content shape (always JSON):

  Retry signal:
    {"retry": True, "reason": <str>, "attempt": <int>}

  Blocked signal (max retries exhausted):
    {"blocked": True, "reason": <str>, "attempts": <int>}

  Pass-through (score OK + grounded):
    original handler ToolMessage is returned unchanged.

Internal state:
  _retry_count: int — resets to 0 after a successful pass (scenario 9).

-------------------------------------------------------------------
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage


# ---------------------------------------------------------------------------
# Helpers — build fake ToolCallRequest and stub handler return values
# ---------------------------------------------------------------------------


def _make_request(
    tool_name: str = "think_tool",
    args: dict[str, Any] | None = None,
    tool_id: str = "call_think_001",
) -> Any:
    """Construct a minimal fake ToolCallRequest compatible with AgentMiddleware."""

    class _FakeRequest:
        tool_call = {
            "name": tool_name,
            "id": tool_id,
            "args": args or {},
        }

    return _FakeRequest()


def _make_handler_return(
    *,
    parsed_score: float | None = 0.85,
    reflection_text: str = "Score: 0.85. References to stage3_TGFB1.json found.",
    tool_id: str = "call_think_001",
) -> ToolMessage:
    """Return a ToolMessage whose content matches the think_tool output schema."""
    payload = {
        "success": True,
        "result": reflection_text,
        "parsed_score": parsed_score,
        "should_continue": False,
        "iteration": 1,
        "max_iterations": 3,
        "score_threshold": 0.7,  # LLM-side default — middleware must IGNORE this
    }
    return ToolMessage(content=json.dumps(payload), tool_call_id=tool_id)


# ---------------------------------------------------------------------------
# Import under test — fails RED until think_tool_quality_gate.py exists
# ---------------------------------------------------------------------------

# This import is intentionally at module level so the entire test file fails
# with ImportError in RED state.
from src.agents.deep_interpreter.middleware.think_tool_quality_gate import (  # noqa: E402
    ThinkToolQualityGateMiddleware,
)


# ---------------------------------------------------------------------------
# Scenario 1: low score → middleware returns retry ToolMessage
# ---------------------------------------------------------------------------


def test_think_tool_quality_gate_low_score_returns_retry() -> None:
    """D2: parsed_score=0.15 is below min_score=0.7 → retry ToolMessage returned.

    Contract: returned ToolMessage.content is JSON with {"retry": True, ...}.
    The underlying handler IS called (score check is post-handler), but the
    handler's ToolMessage is NOT passed through.
    """
    # Arrange
    middleware = ThinkToolQualityGateMiddleware(min_score=0.7, max_retries=2)
    handler = MagicMock(
        return_value=_make_handler_return(
            parsed_score=0.15,
            reflection_text="Score: 0.15. Some context about stage3_TGFB1.json.",
        )
    )
    request = _make_request()

    # Act
    result = middleware.wrap_tool_call(request, handler)

    # Assert
    handler.assert_called_once_with(request)
    assert isinstance(result, ToolMessage)
    payload = json.loads(result.content)
    assert payload.get("retry") is True, f"Expected retry=True, got: {payload}"
    assert "reason" in payload, "Retry ToolMessage must include 'reason'"
    assert isinstance(payload.get("attempt"), int), "Retry ToolMessage must include attempt count"


# ---------------------------------------------------------------------------
# Scenario 2: high score + grounded → pass through
# ---------------------------------------------------------------------------


def test_think_tool_quality_gate_passing_score_passes_through() -> None:
    """D2: parsed_score=0.85 >= 0.7 and reflection is grounded → handler result returned.

    Contract: the exact ToolMessage returned by handler is passed through unchanged.
    """
    # Arrange
    middleware = ThinkToolQualityGateMiddleware(min_score=0.7, max_retries=2)
    original_tm = _make_handler_return(
        parsed_score=0.85,
        reflection_text="Score: 0.85. References to stage3_TGFB1.json found. Value: 0.85.",
    )
    handler = MagicMock(return_value=original_tm)
    request = _make_request()

    # Act
    result = middleware.wrap_tool_call(request, handler)

    # Assert
    handler.assert_called_once_with(request)
    assert result is original_tm, (
        "Passing score + grounded reflection: handler ToolMessage must be returned as-is"
    )


# ---------------------------------------------------------------------------
# Scenario 3: parsed_score=None (regex failed upstream) → strict retry (D4)
# ---------------------------------------------------------------------------


def test_think_tool_quality_gate_none_score_strict_retry() -> None:
    """D4: parsed_score=None means the MCP regex failed → strict fail, retry returned.

    Advisory mode (skip gate) is FORBIDDEN per D4.
    """
    # Arrange
    middleware = ThinkToolQualityGateMiddleware(min_score=0.7, max_retries=2)
    handler = MagicMock(
        return_value=_make_handler_return(
            parsed_score=None,
            reflection_text="No score found in this response. Found stage3_TGFB1.json.",
        )
    )
    request = _make_request()

    # Act
    result = middleware.wrap_tool_call(request, handler)

    # Assert
    handler.assert_called_once_with(request)
    assert isinstance(result, ToolMessage)
    payload = json.loads(result.content)
    assert payload.get("retry") is True, (
        f"D4: None parsed_score must cause retry, got: {payload}"
    )


# ---------------------------------------------------------------------------
# Scenario 4: score passes but reflection is ungrounded → retry (R2)
# ---------------------------------------------------------------------------


def test_think_tool_quality_gate_ungrounded_reflection_returns_retry() -> None:
    """R2: reflection text with no filename pattern and no numeric pattern → retry.

    Even though parsed_score=0.85 passes D2, the absence of grounding signals
    (no '[a-z0-9_]+.json' OR digits) must trigger a retry.
    """
    # Arrange
    middleware = ThinkToolQualityGateMiddleware(min_score=0.7, max_retries=2)
    # Reflection text has no filenames and no numbers whatsoever
    ungrounded_text = "The interpretation looks qualitatively adequate. Seems fine overall."
    handler = MagicMock(
        return_value=_make_handler_return(
            parsed_score=0.85,
            reflection_text=ungrounded_text,
        )
    )
    request = _make_request()

    # Act
    result = middleware.wrap_tool_call(request, handler)

    # Assert
    handler.assert_called_once_with(request)
    assert isinstance(result, ToolMessage)
    payload = json.loads(result.content)
    assert payload.get("retry") is True, (
        f"R2: ungrounded reflection must trigger retry regardless of score, got: {payload}"
    )


# ---------------------------------------------------------------------------
# Scenario 5: max_retries exhausted → BLOCKED ToolMessage
# ---------------------------------------------------------------------------


def test_think_tool_quality_gate_max_retries_exhausted_returns_blocked() -> None:
    """D3: after max_retries=2 consecutive failures, BLOCKED is returned (not retry).

    Contract: {"blocked": True, "reason": ..., "attempts": 2}
    """
    # Arrange
    middleware = ThinkToolQualityGateMiddleware(min_score=0.7, max_retries=2)
    failing_handler = MagicMock(
        return_value=_make_handler_return(
            parsed_score=0.15,
            reflection_text="Score: 0.15. stage3_TGFB1.json mentioned.",
        )
    )
    request = _make_request()

    # Act — invoke enough times to exhaust retries
    # First two calls → retry (attempts 1 and 2)
    result_1 = middleware.wrap_tool_call(request, failing_handler)
    result_2 = middleware.wrap_tool_call(request, failing_handler)
    # Third call after max_retries=2 exhausted → BLOCKED
    result_3 = middleware.wrap_tool_call(request, failing_handler)

    # Assert intermediate retries
    assert json.loads(result_1.content).get("retry") is True
    assert json.loads(result_2.content).get("retry") is True

    # Assert final block
    assert isinstance(result_3, ToolMessage)
    payload = json.loads(result_3.content)
    assert payload.get("blocked") is True, (
        f"D3: after max_retries=2 failures, must return blocked=True, got: {payload}"
    )
    assert "attempts" in payload, "BLOCKED ToolMessage must include 'attempts'"
    assert payload["attempts"] == 2
    assert failing_handler.call_count == 3


# ---------------------------------------------------------------------------
# Scenario 6: LLM injects score_threshold=0.0 → middleware ignores it (D5 clamp)
# ---------------------------------------------------------------------------


def test_think_tool_quality_gate_clamps_llm_score_threshold() -> None:
    """D5: LLM-supplied score_threshold=0.0 in request args is silently ignored.

    The server-side min_score=0.7 must still be applied.
    parsed_score=0.5 is below 0.7, so retry is expected even though LLM asked for 0.0.
    """
    # Arrange
    middleware = ThinkToolQualityGateMiddleware(min_score=0.7, max_retries=2)
    # LLM injected score_threshold=0.0 in the request args
    request = _make_request(args={"score_threshold": 0.0, "reflection": "some text"})
    handler = MagicMock(
        return_value=_make_handler_return(
            parsed_score=0.5,
            reflection_text="Score: 0.5. Found stage3_TGFB1.json and value 0.5.",
        )
    )

    # Act
    result = middleware.wrap_tool_call(request, handler)

    # Assert
    handler.assert_called_once_with(request)
    payload = json.loads(result.content)
    assert payload.get("retry") is True, (
        f"D5: LLM score_threshold=0.0 must be ignored; min_score=0.7 must apply, got: {payload}"
    )


# ---------------------------------------------------------------------------
# Scenario 7: THINK_TOOL_MIN_SCORE env override → lower threshold applied
# ---------------------------------------------------------------------------


def test_think_tool_quality_gate_env_override_min_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """D2 + env: THINK_TOOL_MIN_SCORE=0.6 → 0.6 threshold; parsed_score=0.65 → pass.

    With default threshold 0.7, parsed_score=0.65 would fail.
    With env override 0.6, it should pass (assuming reflection is grounded).
    """
    # Arrange
    monkeypatch.setenv("THINK_TOOL_MIN_SCORE", "0.6")
    # Middleware reads env at construction time OR at call time — both acceptable.
    middleware = ThinkToolQualityGateMiddleware()  # no explicit args → reads env
    grounded_text = "Score: 0.65. See stage3_TGFB1.json for details. Value: 0.65."
    original_tm = _make_handler_return(parsed_score=0.65, reflection_text=grounded_text)
    handler = MagicMock(return_value=original_tm)
    request = _make_request()

    # Act
    result = middleware.wrap_tool_call(request, handler)

    # Assert
    handler.assert_called_once_with(request)
    assert result is original_tm, (
        "With THINK_TOOL_MIN_SCORE=0.6, parsed_score=0.65 must pass through"
    )


# ---------------------------------------------------------------------------
# Scenario 8: THINK_TOOL_MAX_RETRIES=1 env override → blocked after 1 retry
# ---------------------------------------------------------------------------


def test_think_tool_quality_gate_env_override_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """D3 + env: THINK_TOOL_MAX_RETRIES=1 → BLOCKED after only 1 retry attempt."""
    # Arrange
    monkeypatch.setenv("THINK_TOOL_MAX_RETRIES", "1")
    middleware = ThinkToolQualityGateMiddleware()  # reads env
    failing_handler = MagicMock(
        return_value=_make_handler_return(
            parsed_score=0.15,
            reflection_text="Score: 0.15. stage3_TGFB1.json present.",
        )
    )
    request = _make_request()

    # Act — first call should be retry, second should be BLOCKED
    result_1 = middleware.wrap_tool_call(request, failing_handler)
    result_2 = middleware.wrap_tool_call(request, failing_handler)

    # Assert
    assert json.loads(result_1.content).get("retry") is True
    payload_2 = json.loads(result_2.content)
    assert payload_2.get("blocked") is True, (
        f"With THINK_TOOL_MAX_RETRIES=1, second call must be blocked, got: {payload_2}"
    )
    assert payload_2.get("attempts") == 1


# ---------------------------------------------------------------------------
# Scenario 9: successful pass resets internal retry counter to 0
# ---------------------------------------------------------------------------


def test_think_tool_quality_gate_success_resets_retry_counter() -> None:
    """After a passing call, the internal _retry_count resets to 0.

    Sequence:
      - Call 1: parsed_score=0.15 → retry (count=1)
      - Call 2: parsed_score=0.85 + grounded → pass (count resets to 0)
      - Call 3: parsed_score=0.15 → retry again (count=1, not blocked)

    If the counter were NOT reset, Call 3 would already exhaust max_retries=2
    and return BLOCKED after only one failure since the reset.
    """
    # Arrange
    middleware = ThinkToolQualityGateMiddleware(min_score=0.7, max_retries=2)

    fail_tm = _make_handler_return(
        parsed_score=0.15,
        reflection_text="Score: 0.15. stage3_TGFB1.json mentioned. Value: 0.15.",
        tool_id="call_think_001",
    )
    pass_tm = _make_handler_return(
        parsed_score=0.85,
        reflection_text="Score: 0.85. stage3_TGFB1.json found. Value: 0.85.",
        tool_id="call_think_002",
    )

    request_fail = _make_request(tool_id="call_think_001")
    request_pass = _make_request(tool_id="call_think_002")

    handler_fail = MagicMock(return_value=fail_tm)
    handler_pass = MagicMock(return_value=pass_tm)

    # Act
    result_1 = middleware.wrap_tool_call(request_fail, handler_fail)  # retry, count=1
    result_2 = middleware.wrap_tool_call(request_pass, handler_pass)  # pass, count→0
    result_3 = middleware.wrap_tool_call(request_fail, handler_fail)  # retry, count=1 again

    # Assert
    assert json.loads(result_1.content).get("retry") is True, "Call 1 must be retry"
    assert result_2 is pass_tm, "Call 2 must pass through (count reset)"

    payload_3 = json.loads(result_3.content)
    assert payload_3.get("retry") is True, (
        "Call 3 must be retry (not blocked), proving counter was reset after success; "
        f"got: {payload_3}"
    )
    assert payload_3.get("blocked") is not True, (
        "Call 3 must NOT be blocked — counter was reset by the successful pass"
    )


# ---------------------------------------------------------------------------
# Async coverage: awrap_tool_call path (F2 — CV-P1-001)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_awrap_tool_call_low_score_returns_retry_async() -> None:
    """D2 async path: parsed_score=0.15 < min_score=0.7 → retry ToolMessage via awrap_tool_call.

    Mirrors scenario 1 (test_think_tool_quality_gate_low_score_returns_retry)
    but exercises the async code path.
    """
    # Arrange
    middleware = ThinkToolQualityGateMiddleware(min_score=0.7, max_retries=2)
    request = _make_request()
    handler_return = _make_handler_return(
        parsed_score=0.15,
        reflection_text="Score: 0.15. Some context about stage3_TGFB1.json.",
    )

    async def async_handler(req: object) -> ToolMessage:
        return handler_return

    # Act
    result = await middleware.awrap_tool_call(request, async_handler)

    # Assert
    assert isinstance(result, ToolMessage)
    payload = json.loads(result.content)
    assert payload.get("retry") is True, (
        f"awrap_tool_call: expected retry=True for low score, got: {payload}"
    )
    assert "reason" in payload, "Retry ToolMessage must include 'reason'"
    assert isinstance(payload.get("attempt"), int), "Retry ToolMessage must include attempt count"
