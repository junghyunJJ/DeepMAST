"""Graph builder for CCI Interpreter Agent.

This module provides the graph builder function for LangGraph CLI integration.
The CCI Interpreter uses the Deep Agents framework (create_deep_agent).

Two graph variants are available:
1. cci_interpreter_graph: Original Deep Agent with HITL target-selector (may be unreliable)
2. cci_interpreter_wrapped_graph: Wrapper agent with pre-collection pattern (recommended)
"""

from langchain_core.runnables import Runnable

from src.agents.cci_interpreter.cci_interpreter_agent import (
    create_cci_interpreter_agent,
    CCIInterpreterConfig,
)
from src.agents.cci_interpreter.cci_interpreter_wrapper_agent import (
    CCIInterpreterWrapperAgent,
)
from src.agents.model import create_llm


def create_cci_interpreter_graph(
    model: str = "anthropic:claude-sonnet-4-20250514",
    use_checkpointer: bool = True,
    is_debug: bool = False,
) -> Runnable:
    """Create CCI Interpreter graph for LangGraph deployment.

    The CCI Interpreter uses the Deep Agents framework which provides:
    - FilesystemMiddleware for context management
    - TodoListMiddleware for task tracking
    - SubAgentMiddleware for specialized subagents
    - HITL support via interrupt_on configuration

    Args:
        model: LLM model identifier
        use_checkpointer: Whether to use memory checkpointer
        is_debug: Enable debug mode

    Returns:
        Compiled Deep Agent runnable
    """
    config = CCIInterpreterConfig(
        model=model,
        use_checkpointer=use_checkpointer,
    )

    return create_cci_interpreter_agent(config)


def _get_cci_interpreter_graph() -> Runnable:
    """CCI Interpreter graph (sync wrapper) - for LangGraph CLI.

    Note: Deep Agents create_deep_agent() is synchronous, so no async
    wrapper is needed unlike the other agents.

    Returns:
        Compiled Deep Agent runnable
    """
    return create_cci_interpreter_graph(
        model='openai:gpt-4.1-mini',
        use_checkpointer=False,  # LangGraph CLI uses its own persistence
        is_debug=False,
    )


def create_cci_interpreter_graph_wrapped(
    model: str = "openai:gpt-4.1-mini",
    use_checkpointer: bool = False,
    is_debug: bool = False,
) -> Runnable:
    """Create wrapped CCI Interpreter graph with pre-collection pattern.

    This variant uses the wrapper agent pattern where:
    1. Wrapper collects data_directory, clusters/celltypes from user (HITL)
    2. Wrapper writes /targets.json to filesystem
    3. Wrapper invokes Deep Agent with readonly target-selector

    This resolves the HITL issues where Deep Agents' interrupt_on doesn't
    work reliably at the subagent level.

    Args:
        model: LLM model identifier
        use_checkpointer: Whether to use memory checkpointer
        is_debug: Enable debug mode

    Returns:
        Compiled Wrapper Agent runnable
    """
    # Create LLM using the model factory
    llm = create_llm(provider="openai")

    # Create Deep Agent config for the wrapped version
    deep_agent_config = CCIInterpreterConfig(
        model=model,
        use_checkpointer=use_checkpointer,
        use_readonly_selector=True,  # Always use readonly selector
    )

    # Create wrapper agent
    wrapper = CCIInterpreterWrapperAgent(
        model=llm,
        is_debug=is_debug,
        deep_agent_config=deep_agent_config,
    )

    # Return compiled graph (BaseAgent builds graph in __init__)
    return wrapper.graph


def _get_cci_interpreter_graph_wrapped() -> Runnable:
    """Wrapped CCI Interpreter graph - for LangGraph CLI.

    This is the recommended variant that uses the wrapper agent pattern
    for reliable HITL target selection.

    Returns:
        Compiled Wrapper Agent runnable
    """
    return create_cci_interpreter_graph_wrapped(
        model='openai:gpt-4.1-mini',
        use_checkpointer=False,  # LangGraph CLI uses its own persistence
        is_debug=False,
    )


# LangGraph CLI exports
# Original Deep Agent (may have HITL issues)
cci_interpreter_graph = _get_cci_interpreter_graph()

# Wrapped version with reliable HITL (RECOMMENDED)
cci_interpreter_wrapped_graph = _get_cci_interpreter_graph_wrapped()


__all__ = [
    "create_cci_interpreter_graph",
    "create_cci_interpreter_graph_wrapped",
    "cci_interpreter_graph",
    "cci_interpreter_wrapped_graph",
]
