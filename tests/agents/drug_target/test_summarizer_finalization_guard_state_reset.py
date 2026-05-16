"""Task #8 tests: SummarizerFinalizationGuardMiddleware resets state between runs.

Test IDs:
  SFG-R-01  test_summarizer_finalization_guard_resets_between_runs
  SFG-R-02  test_summarizer_finalization_guard_still_gates_html_after_reset
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage

from src.agents.drug_target.subagents.summarizer.middleware import (
    SummarizerFinalizationGuardMiddleware,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_validator_request() -> MagicMock:
    """Build a minimal ToolCallRequest-like mock for validate_drug_md."""
    req = MagicMock()
    req.tool_call = {
        "name": "validate_drug_md",
        "id": "tool-call-validate-001",
        "args": {},
    }
    return req


def _make_html_request() -> MagicMock:
    """Build a minimal ToolCallRequest-like mock for generate_drug_html_report."""
    req = MagicMock()
    req.tool_call = {
        "name": "generate_drug_html_report",
        "id": "tool-call-html-001",
        "args": {},
    }
    return req


def _valid_validator_result() -> ToolMessage:
    """Return a ToolMessage representing a passing validate_drug_md response."""
    return ToolMessage(
        content=json.dumps({"valid": True, "issues": []}),
        tool_call_id="tool-call-validate-001",
    )


def _set_valid_state(mw: SummarizerFinalizationGuardMiddleware) -> None:
    """Drive the middleware into a 'validator passed' state via wrap_tool_call."""
    validate_req = _make_validator_request()
    handler = MagicMock(return_value=_valid_validator_result())
    mw.wrap_tool_call(validate_req, handler)


# ---------------------------------------------------------------------------
# SFG-R-01: before_agent clears all per-run state
# ---------------------------------------------------------------------------


def test_summarizer_finalization_guard_resets_between_runs() -> None:
    """before_agent must clear _validator_called and _last_valid so that a
    previous run's valid=true cannot bleed into a subsequent run.

    Pattern mirrors test_critic_gate_resets_between_summarizer_runs (CG-07).
    """
    mw = SummarizerFinalizationGuardMiddleware()

    # Drive middleware into "validator passed" state (simulates first run)
    _set_valid_state(mw)

    assert mw._validator_called is True
    assert mw._last_valid is True

    # Simulate new summarizer invocation by calling before_agent
    mw.before_agent(state={}, runtime=MagicMock())

    # State must be cleared
    assert mw._validator_called is False, (
        "_validator_called must be False after before_agent reset"
    )
    assert mw._last_valid is None or mw._last_valid is False, (
        "_last_valid must be cleared (None or False) after before_agent reset"
    )

    # Second reset must be idempotent
    mw.before_agent(state={}, runtime=MagicMock())
    assert mw._validator_called is False


# ---------------------------------------------------------------------------
# SFG-R-02: gate blocks HTML after reset even if previous run passed
# ---------------------------------------------------------------------------


def test_summarizer_finalization_guard_still_gates_html_after_reset() -> None:
    """After before_agent reset, generate_drug_html_report must be blocked until
    a fresh validate_drug_md call returns valid=true.

    This is the critical leak-prevention check: reset must make the gate
    behave as if no validator call has occurred in the current run.
    """
    mw = SummarizerFinalizationGuardMiddleware()

    # First run: validator passes
    _set_valid_state(mw)

    # Reset via before_agent (simulates new summarizer invocation)
    mw.before_agent(state={}, runtime=MagicMock())

    # Attempt to generate HTML immediately — must be blocked
    html_req = _make_html_request()
    html_handler = MagicMock()
    result = mw.wrap_tool_call(html_req, html_handler)

    html_handler.assert_not_called()
    assert isinstance(result, ToolMessage)
    blocked_payload = json.loads(result.content)
    assert blocked_payload.get("ok") is False
    assert "validate_drug_md" in blocked_payload.get("error", ""), (
        "Error message must mention validate_drug_md so the LLM knows what to call first"
    )
    assert blocked_payload.get("blocked_by") == "SummarizerFinalizationGuard"

    # Now call validator and then HTML — must be allowed
    validate_req = _make_validator_request()
    validate_handler = MagicMock(return_value=_valid_validator_result())
    mw.wrap_tool_call(validate_req, validate_handler)

    html_req2 = _make_html_request()
    expected_html_result = ToolMessage(content="<html>...</html>", tool_call_id="tool-call-html-001")
    html_handler2 = MagicMock(return_value=expected_html_result)
    result2 = mw.wrap_tool_call(html_req2, html_handler2)

    html_handler2.assert_called_once_with(html_req2)
    assert result2 is expected_html_result
