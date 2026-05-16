"""Spike test: SubAgentMiddleware with a nested critic subagent.

OBSERVED SHAPE (recorded 2026-05-15, deepagents installed version):
--------------------------------------------------------------------
Calling task_tool.invoke({'description': 'ping', 'subagent_type': 'critic', 'runtime': runtime})
returns:

    Command(
        update={
            "messages": [
                ToolMessage(
                    content='{"valid": true, "payload_hash": "sha256:...", ...}',
                    tool_call_id="<tool_call_id>",
                )
            ]
        }
    )

Key findings for CriticGateMiddleware (task #7):
- Import: ``from deepagents import SubAgentMiddleware``  (NOT langchain.agents.middleware)
- ``SubAgentMiddleware.tools[0]`` is the installed ``task`` StructuredTool.
- The task tool accepts ``CompiledSubAgent`` dicts (name, description, runnable) so a
  stub runnable can replace the real LLM for testing without a live API call.
- ``result.update["messages"]`` is always a 1-element list containing a ToolMessage.
- ``ToolMessage.content`` is the JSON-serialised critic output (string, parseable).
- ``result.update`` has no keys other than ``"messages"`` (todos/structured_response
  are excluded by _EXCLUDED_STATE_KEYS inside SubAgentMiddleware).

ToolRuntime required positional fields (all must be provided; none have defaults):
    state, context, config, stream_writer, tools, tool_call_id, store
Optional: execution_info (default None), server_info (default None).

DO NOT modify production code in this test — this is a read-only spike.
"""

from __future__ import annotations

import json

import pytest
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from deepagents import SubAgentMiddleware
from src.agents.drug_target.subagents.critic import get_critic_subagent


# ---------------------------------------------------------------------------
# Appendix A pass body — canned critic response with valid=true
# ---------------------------------------------------------------------------

_PASS_BODY: dict = {
    "valid": True,
    "payload_hash": "sha256:spike-test-fixture",
    "findings_count": 0,
    "findings": [],
}
_PASS_JSON: str = json.dumps(_PASS_BODY)


# ---------------------------------------------------------------------------
# Stub critic runnable — replaces the real LLM with a canned JSON response
# ---------------------------------------------------------------------------


class _StubCriticRunnable:
    """Minimal runnable stub that returns Appendix A pass JSON without LLM calls.

    Must return ``{"messages": [...]}`` so that SubAgentMiddleware can extract
    ``result["messages"][-1].text`` as the ToolMessage content.
    """

    def invoke(self, state: dict) -> dict:
        return {"messages": [AIMessage(content=_PASS_JSON)]}

    async def ainvoke(self, state: dict) -> dict:
        return self.invoke(state)


# ---------------------------------------------------------------------------
# Spike test
# ---------------------------------------------------------------------------


def test_nested_subagent_middleware_spike_returns_command_update_messages() -> None:
    """Gate: SubAgentMiddleware + task StructuredTool returns the exact Command shape
    that CriticGateMiddleware (task #7) must parse.

    Assertions (Appendix A contract):
    1. result is langgraph.types.Command
    2. result.update["messages"][-1] is langchain_core.messages.ToolMessage
    3. result.update["messages"][-1].content is parseable JSON with valid=True
    """
    # --- Build critic spec (uses production get_critic_subagent for name/prompt) ---
    critic_dict_spec = get_critic_subagent(model="openai:gpt-4o")

    # Wrap with a stub runnable to avoid any real LLM call.
    # CompiledSubAgent shape: name + description + runnable
    critic_compiled = {
        "name": critic_dict_spec["name"],  # "critic"
        "description": "Read-only critic for drug_target summarizer (stub in spike test)",
        "runnable": _StubCriticRunnable(),
    }

    # --- Install SubAgentMiddleware with the stub critic ---
    # backend is required by the constructor signature but is only used when
    # SubAgentMiddleware builds SubAgent (not CompiledSubAgent) runnables.
    # A plain object satisfies the type; it is never called in this test path.
    class _NullBackend:
        pass

    mw = SubAgentMiddleware(
        backend=_NullBackend(),
        subagents=[critic_compiled],  # type: ignore[list-item]
    )

    # Confirm the middleware installed exactly one tool named "task".
    assert len(mw.tools) == 1, "SubAgentMiddleware must install exactly one tool"
    task_tool = mw.tools[0]
    assert task_tool.name == "task", f"Expected tool name 'task', got {task_tool.name!r}"

    # --- Build a minimal ToolRuntime (all required fields; no graph context needed) ---
    runtime = ToolRuntime(
        state={"messages": []},
        context=None,
        config={},
        stream_writer=lambda _: None,
        tools=[],
        tool_call_id="spike-tool-call-id-001",
        store=None,
    )

    # --- Invoke the real task StructuredTool ---
    result = task_tool.invoke(
        {
            "description": "ping — validate critic round-trip shape",
            "subagent_type": "critic",
            "runtime": runtime,
        }
    )

    # -----------------------------------------------------------------------
    # Assertion 1: result must be a langgraph Command
    # -----------------------------------------------------------------------
    assert isinstance(result, Command), (
        f"task tool must return langgraph.types.Command, got {type(result)!r}\n"
        f"Observed shape: {result!r}"
    )

    # -----------------------------------------------------------------------
    # Assertion 2: result.update["messages"][-1] must be a ToolMessage
    # -----------------------------------------------------------------------
    assert "messages" in result.update, (
        f"Command.update must contain 'messages' key. "
        f"Observed keys: {list(result.update.keys())}"
    )
    messages = result.update["messages"]
    assert len(messages) >= 1, "Command.update['messages'] must be non-empty"

    last_message = messages[-1]
    assert isinstance(last_message, ToolMessage), (
        f"Command.update['messages'][-1] must be a ToolMessage, "
        f"got {type(last_message)!r}"
    )

    # -----------------------------------------------------------------------
    # Assertion 3: ToolMessage.content must be parseable JSON with valid=True
    # -----------------------------------------------------------------------
    raw_content: str = last_message.content  # type: ignore[assignment]
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"ToolMessage.content is not valid JSON: {exc}\n"
            f"Raw content: {raw_content!r}"
        )

    assert parsed.get("valid") is True, (
        f"Expected valid=True in critic JSON output, got valid={parsed.get('valid')!r}\n"
        f"Full parsed: {parsed}"
    )

    # -----------------------------------------------------------------------
    # Inline fixture comment — recorded shape for future readers
    # -----------------------------------------------------------------------
    # Command(
    #   update={
    #     "messages": [
    #       ToolMessage(
    #         content='{"valid": true, "payload_hash": "sha256:spike-test-fixture",
    #                   "findings_count": 0, "findings": []}',
    #         tool_call_id="spike-tool-call-id-001",
    #       )
    #     ]
    #   }
    # )
    #
    # CriticGateMiddleware (task #7) must parse result.update["messages"][-1].content
    # as JSON and read the "valid" boolean to decide whether to allow save.
