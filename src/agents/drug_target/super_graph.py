"""Super-graph for Drug Target Assessment.

Topology: START → run_deep_agent → finalize_report → END

The DeepAgents runnable is wrapped as a LangGraph node (run_deep_agent) so
that the deterministic finalize_report node can run after it within a single
StateGraph compilation.

Caller MUST pass initial state with all required keys::

    await drug_target_graph.ainvoke(
        {
            "messages": [],
            "data_dir": "/path/to/workspace",
            "disease": "breast cancer",
            "featured_lr_pairs": None,
            "report_finalization_error": None,
            "evidence_truncated": False,
        },
        config={
            "recursion_limit": 10000,   # TOP-LEVEL key, NOT under configurable
            "configurable": {"thread_id": "..."},
        },
    )
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import TypedDict


class DrugTargetState(TypedDict):
    """State schema for the drug-target super-graph.

    Fields
    ------
    data_dir
        Workspace directory containing lr_candidates.json and evidence/.
        Injected by the caller; all nodes treat this as read-only.
    disease
        Disease context string (e.g. "breast cancer").
        Injected by the caller; finalize_report passes it to _load_expansion_inputs.
    featured_lr_pairs
        Subset of LR pairs selected as "featured" by the evidence assessor.
        Populated externally (wrapper_agent.py) — this super-graph is read-only.
        May be None when not yet determined.
    messages
        Accumulated messages. add_messages reducer appends new messages.
        Caller MUST pass ``[]`` as the initial value.
        run_deep_agent returns exactly one AIMessage (the last one from the
        DeepAgents transcript), so final len == 1.
    report_finalization_error
        Set by finalize_report on any failure. None means success.
    evidence_truncated
        True when finalize_report aborted due to evidence token budget exceeded.
        Default False.
    """

    data_dir: str
    disease: str
    featured_lr_pairs: list[str] | None
    messages: Annotated[list[BaseMessage], add_messages]
    report_finalization_error: str | None
    evidence_truncated: bool


async def run_deep_agent(state: DrugTargetState, config: RunnableConfig) -> dict:
    """LangGraph node: invoke the DeepAgents drug-target runnable.

    Builds the inner DeepAgents runnable via create_drug_target_agent(config)
    and invokes it with the initial message list from state.  Returns only the
    last AIMessage from the transcript to keep checkpoint size bounded.

    The recursion_limit from the top-level RunnableConfig is forwarded to the
    inner runnable (CP-P1-014 fix: read from config top-level, NOT
    config["configurable"]).
    """
    # Lazy import to avoid circular dependency at module load time
    import os
    from typing import Literal as _Lit, cast as _cast

    from langchain_core.runnables import RunnableConfig as _RC

    from src.agents.drug_target.agent import DrugTargetConfig, create_drug_target_agent

    data_dir: str = state["data_dir"]
    disease: str = state["disease"]

    # Read provider from env — DrugTargetConfig.provider is a Literal; cast for pyright.
    provider_str = os.getenv("LLM_PROVIDER", "openrouter")
    provider = _cast(
        _Lit["openai", "google", "ollama", "ollama-openai", "claude", "openrouter"],
        provider_str,
    )

    agent_config = DrugTargetConfig(
        provider=provider,
        data_dir=data_dir,
        disease=disease,
        use_checkpointer=False,
    )
    runnable, backend = create_drug_target_agent(agent_config)

    # recursion_limit is a top-level RunnableConfig key (CP-P1-014)
    recursion_limit: int = config.get("recursion_limit", 10000)
    inner_config: _RC = _RC(
        recursion_limit=recursion_limit,
        configurable=config.get("configurable", {}),
    )

    try:
        result = await runnable.ainvoke(
            {"messages": state["messages"]},
            config=inner_config,
        )
    finally:
        if backend is not None and hasattr(backend, "cleanup"):
            backend.cleanup()  # type: ignore[union-attr]

    # Filter to last AIMessage only — blocks trailing ToolMessages from being
    # stored in the checkpoint (CP-P0-009 messages contract).
    ai_messages = [m for m in result.get("messages", [])[-3:] if isinstance(m, AIMessage)]
    return {"messages": ai_messages[-1:]}


def build_drug_target_super_graph() -> CompiledStateGraph:
    """Build and compile the drug-target super-graph.

    Topology: START → run_deep_agent → finalize_report → END
    All edges are static (no conditional routing needed — finalize_report
    always returns a plain dict and the static edge routes to END regardless
    of error state).

    Note: do NOT pass ``recursion_limit`` to ``.compile()`` — pass it at
    invocation time via ``config={"recursion_limit": N}``.
    """
    from src.agents.drug_target.finalize_report import finalize_report

    graph = StateGraph(DrugTargetState)
    graph.add_node("run_deep_agent", run_deep_agent)  # type: ignore[arg-type]
    graph.add_node("finalize_report", finalize_report)  # type: ignore[arg-type]

    graph.add_edge(START, "run_deep_agent")
    graph.add_edge("run_deep_agent", "finalize_report")
    graph.add_edge("finalize_report", END)

    return graph.compile()
