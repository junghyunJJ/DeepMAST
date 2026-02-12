"""Graph builder for Supervisor Agent.

This module provides the graph builder function for LangGraph CLI integration.
The Supervisor orchestrates Pipeline Builder → Deep Interpreter workflow.
"""

import os

from dotenv import load_dotenv
from langchain_core.runnables import Runnable

load_dotenv()

from src.agents.supervisor.supervisor_agent import SupervisorAgent  # noqa: E402
from src.agents.model import create_llm  # noqa: E402


def create_supervisor_graph(
    provider: str = None,
    is_debug: bool = True,
) -> Runnable:
    """Create Supervisor graph for LangGraph deployment.

    Args:
        provider: LLM provider (defaults to LLM_PROVIDER env var)
        is_debug: Enable debug mode

    Returns:
        Compiled Supervisor Agent graph
    """
    if provider is None:
        provider = os.getenv("LLM_PROVIDER", "openai")

    llm = create_llm(provider=provider)

    agent = SupervisorAgent(
        model=llm,
        is_debug=is_debug,
    )

    return agent.graph


def _get_supervisor_graph() -> Runnable:
    """Supervisor graph (sync wrapper) - for LangGraph CLI."""
    return create_supervisor_graph(is_debug=False)


# LangGraph CLI export
supervisor_graph = _get_supervisor_graph()


__all__ = [
    "create_supervisor_graph",
    "supervisor_graph",
]
