"""Graph builder for Drug Target Assessment Agent.

Provides LangGraph CLI integration for standalone testing and deployment.

Graph: DrugTarget — drug target assessment super-graph
Topology: START → run_deep_agent → finalize_report → END

Invocation contract (HARD — per Decision 1 / CP-P1-014):
    ``recursion_limit`` is a TOP-LEVEL ``RunnableConfig`` key, NOT nested
    under ``configurable``.  Callers MUST use::

        await drug_target_graph.ainvoke(
            initial_state,
            config={
                "recursion_limit": cfg.recursion_limit,
                "configurable": {"thread_id": "..."},
            },
        )

    Passing ``recursion_limit`` inside ``configurable`` is silently ignored
    by LangGraph 0.3+ and will cause the graph to use the default limit.
"""

from dotenv import load_dotenv

load_dotenv()

from src.agents.drug_target.super_graph import build_drug_target_super_graph  # noqa: E402


# LangGraph CLI export — langgraph.json entry path:
#   "DrugTarget": "src.agents.drug_target.graph_builder:drug_target_graph"
# Symbol name MUST stay ``drug_target_graph`` (langgraph.json depends on it).
drug_target_graph = build_drug_target_super_graph()
