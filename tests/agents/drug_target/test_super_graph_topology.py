"""#18b — AC4 + CP-P0-009: Super-graph topology and messages contract.

1. Node set includes run_deep_agent and finalize_report.
2. Static edges: START→run_deep_agent, run_deep_agent→finalize_report,
   finalize_report→END.
3. Messages contract: only the last AIMessage survives after run_deep_agent.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


# ---------------------------------------------------------------------------
# Topology assertions
# ---------------------------------------------------------------------------


def test_graph_contains_required_nodes() -> None:
    """graph must expose run_deep_agent and finalize_report node IDs."""
    from src.agents.drug_target.graph_builder import drug_target_graph

    compiled = drug_target_graph.get_graph()
    node_ids = set(compiled.nodes.keys())

    assert "run_deep_agent" in node_ids, f"run_deep_agent missing from {node_ids}"
    assert "finalize_report" in node_ids, f"finalize_report missing from {node_ids}"


def test_graph_edges_include_required_transitions() -> None:
    """Static edges START→run_deep_agent, run_deep_agent→finalize_report,
    finalize_report→END must all be present."""
    from langgraph.graph import END, START

    from src.agents.drug_target.graph_builder import drug_target_graph

    compiled = drug_target_graph.get_graph()
    edges = [(e.source, e.target) for e in compiled.edges]

    assert (START, "run_deep_agent") in edges, f"Missing START→run_deep_agent in {edges}"
    assert ("run_deep_agent", "finalize_report") in edges, (
        f"Missing run_deep_agent→finalize_report in {edges}"
    )
    assert ("finalize_report", END) in edges, f"Missing finalize_report→END in {edges}"


# ---------------------------------------------------------------------------
# Messages contract (CP-P0-009)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_messages_contract_only_last_ai_message_survives(
    tmp_path,
    monkeypatch,
) -> None:
    """run_deep_agent must return exactly 1 AIMessage; non-AI messages are dropped.

    Strategy: patch create_drug_target_agent (the lazy import inside run_deep_agent)
    to return a fake runnable that yields multiple mixed messages. Pre-write drug.md
    so finalize_report's idempotency guard exits immediately without an LLM call.
    """
    ai_first = AIMessage(content="intermediate reasoning")
    ai_last = AIMessage(content="final answer")
    multi_messages = [
        HumanMessage(content="start"),
        ToolMessage(content="tool result", tool_call_id="tc1"),
        ai_first,
        ai_last,
    ]

    import types

    async def _fake_ainvoke(inp, config=None):
        return {"messages": multi_messages}

    fake_runnable = types.SimpleNamespace(ainvoke=_fake_ainvoke)

    # create_drug_target_agent is imported inside run_deep_agent body at call time;
    # patch at the source module so the local `from … import` resolves to the mock.
    monkeypatch.setattr(
        "src.agents.drug_target.agent.create_drug_target_agent",
        lambda cfg: (fake_runnable, None),
    )

    # Pre-write drug.md so finalize_report's idempotency guard (Decision 12) exits
    # immediately — no LLM call needed and no further patching required.
    (tmp_path / "drug.md").write_text("# pre-existing", encoding="utf-8")

    from src.agents.drug_target.super_graph import build_drug_target_super_graph

    test_graph = build_drug_target_super_graph()

    initial_state = {
        "messages": [],
        "data_dir": str(tmp_path),
        "disease": "test-disease",
        "featured_lr_pairs": None,
        "report_finalization_error": None,
        "evidence_truncated": False,
    }

    final_state = await test_graph.ainvoke(
        initial_state,
        config={"recursion_limit": 100, "configurable": {"thread_id": "test-123"}},
    )

    msgs = final_state["messages"]
    assert len(msgs) == 1, f"Expected 1 message, got {len(msgs)}: {msgs}"
    assert isinstance(msgs[-1], AIMessage), (
        f"Last message must be AIMessage, got {type(msgs[-1])}"
    )
    assert msgs[-1].content == "final answer"


@pytest.mark.asyncio
async def test_messages_contract_with_empty_initial_messages(
    tmp_path,
    monkeypatch,
) -> None:
    """Caller passing messages=[] must still get exactly 1 AIMessage back."""
    ai_msg = AIMessage(content="only answer")

    import types

    async def _fake_ainvoke(inp, config=None):
        return {"messages": [ai_msg]}

    fake_runnable = types.SimpleNamespace(ainvoke=_fake_ainvoke)

    monkeypatch.setattr(
        "src.agents.drug_target.agent.create_drug_target_agent",
        lambda cfg: (fake_runnable, None),
    )

    # idempotency guard so finalize_report is a no-op
    (tmp_path / "drug.md").write_text("# pre-existing", encoding="utf-8")

    from src.agents.drug_target.super_graph import build_drug_target_super_graph

    test_graph = build_drug_target_super_graph()

    initial_state = {
        "messages": [],
        "data_dir": str(tmp_path),
        "disease": "test-disease",
        "featured_lr_pairs": None,
        "report_finalization_error": None,
        "evidence_truncated": False,
    }

    final_state = await test_graph.ainvoke(
        initial_state,
        config={"recursion_limit": 100},
    )

    msgs = final_state["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[-1], AIMessage)
