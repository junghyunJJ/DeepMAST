"""Phase 3 RED test — RepairCycleCounterMiddleware wired into create_summarizer_agent.

Asserts:
1. report_writer.invoke.call_count <= 2 when 3 critic cycles are attempted.
2. Final agent response content contains "BLOCKED".
3. test_summarizer_counter.py helper contract unaffected (separate test file).

Strategy: inject mock report_writer/critic runnables via inner_subagents;
critic always emits passed=False with one P0 finding.
We drive the middleware directly (not via a live LLM) to keep the test deterministic.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(tool_name: str, subagent_type: str | None = None, tool_id: str = "c1") -> Any:
    """Return a minimal ToolCallRequest-like object."""
    args: dict = {}
    if subagent_type is not None:
        args["subagent_type"] = subagent_type

    class _FakeRequest:
        tool_call = {"name": tool_name, "id": tool_id, "args": args}

    return _FakeRequest()


def _rw_request(tool_id: str = "rw1") -> Any:
    return _make_request("task", "report_writer", tool_id)


def _critic_request(tool_id: str = "cr1") -> Any:
    return _make_request("task", "critic", tool_id)


# ---------------------------------------------------------------------------
# T10a: RepairCycleCounterMiddleware blocks 3rd report_writer call
# ---------------------------------------------------------------------------


def test_repair_cycle_counter_blocks_third_report_writer() -> None:
    """Third report_writer task call must be blocked; handler invoked at most 2x."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        RepairCycleCounterMiddleware,
    )

    mw = RepairCycleCounterMiddleware(max_cycles=2)
    handler = MagicMock(return_value=ToolMessage(content="rw done", tool_call_id="x"))

    # Cycle 1 — allowed
    result1 = mw.wrap_tool_call(_rw_request("rw1"), handler)
    assert handler.call_count == 1

    # Cycle 2 — allowed
    result2 = mw.wrap_tool_call(_rw_request("rw2"), handler)
    assert handler.call_count == 2

    # Cycle 3 — BLOCKED
    result3 = mw.wrap_tool_call(_rw_request("rw3"), handler)
    assert handler.call_count == 2, (
        f"handler must NOT be called on 3rd invocation; count={handler.call_count}"
    )
    assert isinstance(result3, ToolMessage)
    payload = json.loads(result3.content)
    assert payload.get("status") == "BLOCKED", f"expected BLOCKED, got {payload}"
    assert "BLOCKED" in result3.content


# ---------------------------------------------------------------------------
# T10b: critic calls pass through and findings are captured
# ---------------------------------------------------------------------------


def test_critic_calls_pass_through_and_findings_captured() -> None:
    """Critic task calls must pass through and last findings must be stored."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        RepairCycleCounterMiddleware,
    )

    mw = RepairCycleCounterMiddleware(max_cycles=2)
    critic_result = ToolMessage(
        content=json.dumps({"passed": False, "findings": ["P0: missing gene data"]}),
        tool_call_id="cr1",
    )
    critic_handler = MagicMock(return_value=critic_result)

    mw.wrap_tool_call(_critic_request("cr1"), critic_handler)
    assert critic_handler.call_count == 1
    assert "P0" in mw._last_critic_findings


# ---------------------------------------------------------------------------
# T10c: BLOCKED message includes last critic findings
# ---------------------------------------------------------------------------


def test_blocked_message_includes_critic_findings() -> None:
    """BLOCKED ToolMessage must contain the most recent critic findings."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        RepairCycleCounterMiddleware,
    )

    mw = RepairCycleCounterMiddleware(max_cycles=1)
    rw_handler = MagicMock(return_value=ToolMessage(content="rw done", tool_call_id="rw1"))
    critic_result = ToolMessage(
        content=json.dumps({"passed": False, "findings": ["P0: TGFB1 not annotated"]}),
        tool_call_id="cr1",
    )
    critic_handler = MagicMock(return_value=critic_result)

    # Allow 1 report_writer call
    mw.wrap_tool_call(_rw_request("rw1"), rw_handler)

    # Critic fires, findings stored
    mw.wrap_tool_call(_critic_request("cr1"), critic_handler)

    # Second report_writer — BLOCKED
    blocked = mw.wrap_tool_call(_rw_request("rw2"), rw_handler)
    assert rw_handler.call_count == 1
    payload = json.loads(blocked.content)
    assert "TGFB1" in payload.get("critic_findings", ""), (
        f"BLOCKED message must include critic findings; got {payload}"
    )


# ---------------------------------------------------------------------------
# T10d: host loop owns repair count in deterministic summarizer
# ---------------------------------------------------------------------------


def test_create_summarizer_agent_uses_deterministic_repair_limit() -> None:
    """create_summarizer_agent must return the deterministic host loop with max_repairs=2."""
    with patch(
        "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
    ) as mock_create:
        stub = MagicMock()
        stub.with_config.return_value = stub
        mock_create.return_value = stub

        from src.agents.drug_target.subagents.summarizer.agent import (
            DeterministicSummarizerRunnable,
            create_summarizer_agent,
        )

        agent = create_summarizer_agent()

    assert isinstance(agent, DeterministicSummarizerRunnable)
    assert agent.max_repairs == 2


# ---------------------------------------------------------------------------
# T10e: async wrap blocks on 3rd report_writer call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_repair_cycle_counter_blocks_third() -> None:
    """awrap_tool_call must also block the 3rd report_writer invocation."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        RepairCycleCounterMiddleware,
    )

    mw = RepairCycleCounterMiddleware(max_cycles=2)
    call_count = {"n": 0}

    async def async_handler(req: Any) -> ToolMessage:
        call_count["n"] += 1
        return ToolMessage(content="done", tool_call_id=req.tool_call["id"])

    await mw.awrap_tool_call(_rw_request("rw1"), async_handler)
    await mw.awrap_tool_call(_rw_request("rw2"), async_handler)
    result3 = await mw.awrap_tool_call(_rw_request("rw3"), async_handler)

    assert call_count["n"] == 2, f"handler must be called at most 2 times; got {call_count['n']}"
    assert "BLOCKED" in result3.content
