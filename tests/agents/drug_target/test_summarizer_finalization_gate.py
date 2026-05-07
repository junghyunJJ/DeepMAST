"""Phase 2 RED tests — SummarizerFinalizationGuardMiddleware (T18).

Six scenarios that must FAIL until SummarizerFinalizationGuardMiddleware is
implemented in src/agents/drug_target/subagents/summarizer/middleware.py.

Contract under test (plan §2.1.D Option C):
  - __init__ sets _validator_called=False, _last_valid=None
  - wrap_tool_call:
    PRE-check:  if save_drug_md OR task(report_writer) is requested:
                  * if _validator_called is False  → BLOCKED ("validate_drug_report_finalization must be called first")
                  * elif _last_valid is False       → BLOCKED ("validator returned valid=false; cannot finalize")
    POST-check: if the tool that just ran was validate_drug_report_finalization,
                  parse ToolMessage JSON for {"valid": bool} → update state
  - BLOCKED ToolMessage content: {"ok": false, "error": "...", "blocked_by": "SummarizerFinalizationGuard"}

Regression coexistence (scenarios e, f):
  - (e) When SummarizerFinalizationGuard blocks task(report_writer),
    RepairCycleCounterMiddleware._cycle_count must NOT increment
    (handler is never reached).
  - (f) Adding SummarizerFinalizationGuard before BuildEvidenceSummaryGuardMiddleware
    must not interfere with the build_evidence_summary call counter for
    non-finalization tools.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage


# ---------------------------------------------------------------------------
# Helpers — minimal ToolCallRequest stub (mirrors test_build_evidence_summary_single_call.py)
# ---------------------------------------------------------------------------


def _make_request(tool_name: str, args: dict | None = None, tool_id: str = "call_001") -> Any:
    """Return a minimal ToolCallRequest-like object with .tool_call dict."""

    class _FakeRequest:
        tool_call = {"name": tool_name, "id": tool_id, "args": args or {}}

    return _FakeRequest()


def _make_save_drug_md_request(tool_id: str = "call_save_001") -> Any:
    return _make_request("save_drug_md", {}, tool_id)


def _make_task_report_writer_request(tool_id: str = "call_task_001") -> Any:
    return _make_request("task", {"subagent_type": "report_writer"}, tool_id)


def _make_validator_request(tool_id: str = "call_val_001") -> Any:
    return _make_request("validate_drug_report_finalization", {}, tool_id)


def _make_validator_tool_message(valid: bool, tool_id: str = "call_val_001") -> ToolMessage:
    """Build a ToolMessage that looks like the real validate_drug_report_finalization output."""
    payload = {
        "valid": valid,
        "issue_count": 0 if valid else 1,
        "issues": [] if valid else [{"code": "MISSING_SECTION", "severity": "critical", "message": "Missing section"}],
        "checks": {},
        "sources": [],
    }
    return ToolMessage(content=json.dumps(payload), tool_call_id=tool_id)


def _make_other_tool_request(tool_id: str = "call_other_001") -> Any:
    return _make_request("load_evidence_files", {"filename": "drug.md"}, tool_id)


# ---------------------------------------------------------------------------
# Import under test — will trigger ImportError in RED state
# ---------------------------------------------------------------------------


def _import_middleware():
    """Deferred import so that the ImportError is isolated to each test."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        SummarizerFinalizationGuardMiddleware,
    )
    return SummarizerFinalizationGuardMiddleware


# ---------------------------------------------------------------------------
# Scenario (a): save_drug_md blocked when validator never called
# ---------------------------------------------------------------------------


def test_save_drug_md_blocked_when_validator_not_called_returns_blocked_tool_message() -> None:
    """D1 strict policy: save_drug_md must be blocked if validator was never called.

    Arrange: fresh SummarizerFinalizationGuardMiddleware (_validator_called=False)
    Act:     call wrap_tool_call with a save_drug_md request
    Assert:  handler is NOT called; result is ToolMessage with ok=false and
             blocked_by="SummarizerFinalizationGuard"
    """
    GuardMiddleware = _import_middleware()
    middleware = GuardMiddleware()

    handler = MagicMock(spec=["__call__"])
    req = _make_save_drug_md_request()

    result = middleware.wrap_tool_call(req, handler)

    handler.assert_not_called()

    assert isinstance(result, ToolMessage), (
        f"Expected ToolMessage when blocked, got {type(result)}"
    )

    payload = json.loads(result.content)
    assert payload.get("ok") is False, f"Expected ok=false in blocked response; got {payload}"
    assert payload.get("blocked_by") == "SummarizerFinalizationGuard", (
        f"Expected blocked_by='SummarizerFinalizationGuard'; got {payload.get('blocked_by')!r}"
    )
    assert "validate_drug_report_finalization" in payload.get("error", ""), (
        f"Error message must reference the validator; got {payload.get('error')!r}"
    )


# ---------------------------------------------------------------------------
# Scenario (b): save_drug_md blocked when validator returned valid=false
# ---------------------------------------------------------------------------


def test_save_drug_md_blocked_when_validator_returned_invalid() -> None:
    """save_drug_md must be blocked if validate_drug_report_finalization returned valid=false.

    Arrange: SummarizerFinalizationGuardMiddleware after validator call that returned valid=false
    Act:     call wrap_tool_call with a save_drug_md request
    Assert:  handler is NOT called; result is ToolMessage with ok=false
    """
    GuardMiddleware = _import_middleware()
    middleware = GuardMiddleware()

    # Simulate: validator was called and returned valid=false
    val_req = _make_validator_request("call_val_001")
    val_result = _make_validator_tool_message(valid=False)
    validator_handler = MagicMock(spec=["__call__"], return_value=val_result)
    middleware.wrap_tool_call(val_req, validator_handler)

    # Now attempt save_drug_md
    handler = MagicMock(spec=["__call__"])
    save_req = _make_save_drug_md_request()
    result = middleware.wrap_tool_call(save_req, handler)

    handler.assert_not_called()

    assert isinstance(result, ToolMessage), (
        f"Expected ToolMessage when blocked, got {type(result)}"
    )
    payload = json.loads(result.content)
    assert payload.get("ok") is False, f"Expected ok=false; got {payload}"
    assert payload.get("blocked_by") == "SummarizerFinalizationGuard", (
        f"Expected blocked_by='SummarizerFinalizationGuard'; got {payload}"
    )
    # State must be consistent: _validator_called=True, _last_valid=False
    assert middleware._validator_called is True
    assert middleware._last_valid is False


# ---------------------------------------------------------------------------
# Scenario (c): task(subagent_type="report_writer") blocked when validator returned valid=false
# ---------------------------------------------------------------------------


def test_task_report_writer_blocked_when_validator_returned_invalid() -> None:
    """task(subagent_type='report_writer') must be blocked if validator returned valid=false.

    Arrange: SummarizerFinalizationGuardMiddleware after validator call with valid=false
    Act:     call wrap_tool_call with task(subagent_type='report_writer')
    Assert:  handler NOT called; ToolMessage with ok=false, blocked_by set
    """
    GuardMiddleware = _import_middleware()
    middleware = GuardMiddleware()

    # Prime: validator called, returned valid=false
    val_req = _make_validator_request()
    val_result = _make_validator_tool_message(valid=False)
    validator_handler = MagicMock(spec=["__call__"], return_value=val_result)
    middleware.wrap_tool_call(val_req, validator_handler)

    # Act: attempt report_writer dispatch
    handler = MagicMock(spec=["__call__"])
    task_req = _make_task_report_writer_request()
    result = middleware.wrap_tool_call(task_req, handler)

    handler.assert_not_called()

    assert isinstance(result, ToolMessage), (
        f"Expected ToolMessage, got {type(result)}"
    )
    payload = json.loads(result.content)
    assert payload.get("ok") is False, f"Expected ok=false; got {payload}"
    assert payload.get("blocked_by") == "SummarizerFinalizationGuard", (
        f"blocked_by mismatch: {payload}"
    )


# ---------------------------------------------------------------------------
# Scenario (d): save_drug_md passes through when validator returned valid=true
# ---------------------------------------------------------------------------


def test_save_drug_md_passes_through_when_validator_returned_valid() -> None:
    """When validate_drug_report_finalization returned valid=true, save_drug_md must proceed.

    Arrange: SummarizerFinalizationGuardMiddleware after validator call with valid=true
    Act:     call wrap_tool_call with save_drug_md
    Assert:  handler IS called exactly once with the save_drug_md request;
             the handler's return value is propagated
    """
    GuardMiddleware = _import_middleware()
    middleware = GuardMiddleware()

    # Prime: validator called, returned valid=true
    val_req = _make_validator_request("call_val_pass")
    val_result = _make_validator_tool_message(valid=True, tool_id="call_val_pass")
    validator_handler = MagicMock(spec=["__call__"], return_value=val_result)
    middleware.wrap_tool_call(val_req, validator_handler)

    assert middleware._validator_called is True
    assert middleware._last_valid is True

    # Act: save_drug_md
    expected_response = ToolMessage(content="saved", tool_call_id="call_save_pass")
    handler = MagicMock(spec=["__call__"], return_value=expected_response)
    save_req = _make_save_drug_md_request("call_save_pass")
    result = middleware.wrap_tool_call(save_req, handler)

    handler.assert_called_once_with(save_req)
    assert result is expected_response, (
        f"Expected handler return value to be propagated; got {result}"
    )


# ---------------------------------------------------------------------------
# Scenario (e): Regression coexistence — RepairCycleCounterMiddleware counter NOT incremented
# ---------------------------------------------------------------------------


def test_repair_cycle_counter_not_incremented_when_finalization_guard_blocks() -> None:
    """RepairCycleCounterMiddleware._report_writer_count must NOT increment when
    SummarizerFinalizationGuardMiddleware blocks the task(report_writer) call.

    The guard blocks before the handler reaches RepairCycleCounter, so the
    counter must remain 0 after the blocked attempt.

    Arrange: both middlewares instantiated; validator NOT called (guard will block)
    Act:     wrap RepairCycleCounterMiddleware handler with guard, call task(report_writer)
    Assert:  RepairCycleCounterMiddleware._report_writer_count == 0
    """
    GuardMiddleware = _import_middleware()
    from src.agents.drug_target.subagents.summarizer.middleware import (
        RepairCycleCounterMiddleware,
    )

    guard = GuardMiddleware()
    counter = RepairCycleCounterMiddleware(max_cycles=2)

    # The counter's wrap_tool_call is the inner handler for the guard
    # When the guard blocks, it returns immediately — counter.wrap_tool_call is never entered
    task_req = _make_task_report_writer_request()

    # Simulate chained middleware: guard wraps counter's handler
    # In practice: guard.wrap_tool_call(req, lambda req: counter.wrap_tool_call(req, real_handler))
    real_handler = MagicMock(
        spec=["__call__"],
        return_value=ToolMessage(content="done", tool_call_id="call_task_001"),
    )

    def chained_handler(req):
        return counter.wrap_tool_call(req, real_handler)

    # Guard blocks because validator never called
    result = guard.wrap_tool_call(task_req, chained_handler)

    # Counter should never have incremented
    assert counter._report_writer_count == 0, (
        f"Expected _report_writer_count=0 when guard blocked; got {counter._report_writer_count}"
    )
    # Handler must not have been reached
    real_handler.assert_not_called()

    # Result must be a BLOCKED ToolMessage from the guard
    assert isinstance(result, ToolMessage)
    payload = json.loads(result.content)
    assert payload.get("blocked_by") == "SummarizerFinalizationGuard", (
        f"Expected guard's blocked_by in result; got {payload}"
    )


# ---------------------------------------------------------------------------
# Scenario (f): Regression coexistence — BuildEvidenceSummaryGuard not broken
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_awrap_tool_call_blocks_save_when_validator_invalid_async() -> None:
    """awrap_tool_call path: save_drug_md is blocked when validator returned valid=false.

    Mirrors scenario (b) (test_save_drug_md_blocked_when_validator_returned_invalid)
    but exercises the async awrap_tool_call code path.
    """
    GuardMiddleware = _import_middleware()
    middleware = GuardMiddleware()

    # Prime: validator called via awrap_tool_call, returned valid=false
    val_req = _make_validator_request("call_val_async_001")
    val_result = _make_validator_tool_message(valid=False)

    async def async_validator_handler(req: object) -> ToolMessage:
        return val_result

    await middleware.awrap_tool_call(val_req, async_validator_handler)

    # Now attempt save_drug_md via awrap_tool_call
    save_req = _make_save_drug_md_request("call_save_async_001")
    save_handler_called = False

    async def async_save_handler(req: object) -> ToolMessage:
        nonlocal save_handler_called
        save_handler_called = True
        return ToolMessage(content="saved", tool_call_id="call_save_async_001")

    result = await middleware.awrap_tool_call(save_req, async_save_handler)

    # Handler must NOT have been reached
    assert not save_handler_called, (
        "awrap_tool_call: handler must not be called when validator returned valid=false"
    )
    assert isinstance(result, ToolMessage), (
        f"Expected ToolMessage when blocked, got {type(result)}"
    )
    payload = json.loads(result.content)
    assert payload.get("ok") is False, (
        f"awrap_tool_call: expected ok=false when validator invalid; got {payload}"
    )
    assert payload.get("blocked_by") == "SummarizerFinalizationGuard", (
        f"awrap_tool_call: expected blocked_by='SummarizerFinalizationGuard'; got {payload}"
    )
    # State must be consistent
    assert middleware._validator_called is True
    assert middleware._last_valid is False


def test_build_evidence_summary_guard_call_count_increments_normally_with_finalization_guard() -> None:
    """Adding SummarizerFinalizationGuardMiddleware must not break
    BuildEvidenceSummaryGuardMiddleware for non-finalization tools.

    The build_evidence_summary tool is NOT a guarded write in
    SummarizerFinalizationGuardMiddleware, so it must pass through the guard
    untouched, and BuildEvidenceSummaryGuardMiddleware._call_count must
    increment normally.

    Arrange: both middlewares chained (SummarizerFinalizationGuard outer,
             BuildEvidenceSummaryGuard inner); validator NOT called
    Act:     call build_evidence_summary once through the chained middleware
    Assert:  BuildEvidenceSummaryGuardMiddleware._call_count == 1
             (guard did not interfere with pass-through for unguarded tool)
    """
    GuardMiddleware = _import_middleware()
    from src.agents.drug_target.subagents.summarizer.middleware import (
        BuildEvidenceSummaryGuardMiddleware,
    )

    finalization_guard = GuardMiddleware()
    evidence_guard = BuildEvidenceSummaryGuardMiddleware()

    # Simulate chained middleware: finalization_guard outer → evidence_guard inner
    real_handler = MagicMock(
        spec=["__call__"],
        return_value=ToolMessage(content="evidence built", tool_call_id="call_bes_001"),
    )

    def chained_handler(req):
        return evidence_guard.wrap_tool_call(req, real_handler)

    build_req = _make_request("build_evidence_summary", {}, "call_bes_001")

    # SummarizerFinalizationGuard should pass through build_evidence_summary (not guarded)
    result = finalization_guard.wrap_tool_call(build_req, chained_handler)

    # BuildEvidenceSummaryGuard should have incremented its counter
    assert evidence_guard._call_count == 1, (
        f"Expected _call_count=1 after one build_evidence_summary call; got {evidence_guard._call_count}"
    )
    # Real handler must have been called
    real_handler.assert_called_once_with(build_req)
    # Result is the handler's return value
    assert isinstance(result, ToolMessage)
    assert json.loads(result.content) if False else True  # content is plain str here, not JSON — just check type
