"""Graph builder for Deep Interpreter Agent.

This module provides the graph builder function for LangGraph CLI integration.
The Deep Interpreter uses the DeepAgents framework (create_deep_agent).

Two graph variants are available:
1. deep_interpreter_graph: Deep Agent with pre-selected targets (no HITL in agent)
2. deep_interpreter_wrapped_graph: Wrapper agent with HITL target collection (recommended)
"""

from typing import Literal

from langchain_core.runnables import Runnable

from src.agents.deep_interpreter.agent import (
    create_deep_interpreter_agent,
    DeepInterpreterConfig,
)
from src.agents.deep_interpreter.wrapper_agent import (
    DeepInterpreterWrapperAgent,
)
from src.agents.model import create_llm


def create_deep_interpreter_graph(
    provider: Literal["openai", "google", "ollama"] = "ollama",
    data_dir: str = "/tmp/deep_interpreter_workspace",
    use_checkpointer: bool = True,
    is_debug: bool = False,
) -> Runnable:
    """Create Deep Interpreter graph for LangGraph deployment.

    The Deep Interpreter uses the DeepAgents framework which provides:
    - FilesystemMiddleware for context management
    - TodoListMiddleware for task tracking
    - SubAgentMiddleware for specialized subagents (11 subagents)
    - Quality validation loop (think_tool, max 3 iterations)
    - CompositeBackend with FilesystemBackend for persistent file storage

    NOTE: This variant expects targets to be pre-selected. For interactive
    target selection, use deep_interpreter_wrapped_graph instead.

    Args:
        provider: LLM provider ('openai', 'google', 'ollama')
        data_dir: Directory for CCI analysis results and agent workspace
        use_checkpointer: Whether to use memory checkpointer
        is_debug: Enable debug mode

    Returns:
        Compiled Deep Agent runnable
    """
    config = DeepInterpreterConfig(
        provider=provider,
        data_dir=data_dir,
        use_checkpointer=use_checkpointer,
    )

    return create_deep_interpreter_agent(config)


def _get_deep_interpreter_graph() -> Runnable:
    """Deep Interpreter graph (sync wrapper) - for LangGraph CLI.

    Note: DeepAgents create_deep_agent() is synchronous, so no async
    wrapper is needed unlike the other agents.

    Returns:
        Compiled Deep Agent runnable
    """
    return create_deep_interpreter_graph(
        provider='ollama',
        use_checkpointer=False,  # LangGraph CLI uses its own persistence
        is_debug=False,
    )


def create_deep_interpreter_graph_wrapped(
    provider: Literal["openai", "google", "ollama"] = "ollama",
    data_dir: str = "/tmp/deep_interpreter_workspace",
    use_checkpointer: bool = False,
    is_debug: bool = False,
) -> Runnable:
    """Create wrapped Deep Interpreter graph with HITL target collection.

    This variant uses the wrapper agent pattern where:
    1. Wrapper collects data_directory, analysis_mode, clusters/celltypes from user (HITL)
    2. Wrapper validates the selection using Pydantic model
    3. Wrapper writes /targets.json to filesystem
    4. Wrapper invokes Deep Agent with readonly target-selector

    This is the RECOMMENDED variant for interactive use.

    Note: The data_dir can be provided as a default, but the wrapper agent
    may override it with the user-provided data_directory during HITL.

    Args:
        provider: LLM provider ('openai', 'google', 'ollama')
        data_dir: Default directory for CCI analysis results and agent workspace
        use_checkpointer: Whether to use memory checkpointer
        is_debug: Enable debug mode

    Returns:
        Compiled Wrapper Agent runnable
    """
    # Create LLM using the model factory (uses environment variables)
    llm = create_llm(provider=provider)

    # Create Deep Agent config for the wrapped version
    # Note: data_dir may be overridden by wrapper based on user input
    deep_agent_config = DeepInterpreterConfig(
        provider=provider,
        data_dir=data_dir,
        use_checkpointer=use_checkpointer,
    )

    # Create wrapper agent
    wrapper = DeepInterpreterWrapperAgent(
        model=llm,
        is_debug=is_debug,
        deep_agent_config=deep_agent_config,
    )

    # Return compiled graph (BaseAgent builds graph in __init__)
    return wrapper.graph


def _get_deep_interpreter_graph_wrapped() -> Runnable:
    """Wrapped Deep Interpreter graph - for LangGraph CLI.

    This is the recommended variant that uses the wrapper agent pattern
    for reliable HITL target selection.

    Returns:
        Compiled Wrapper Agent runnable
    """
    return create_deep_interpreter_graph_wrapped(
        provider='ollama',
        use_checkpointer=False,  # LangGraph CLI uses its own persistence
        is_debug=False,
    )


# LangGraph CLI exports
# Deep Agent (expects pre-selected targets)
deep_interpreter_graph = _get_deep_interpreter_graph()

# Wrapped version with HITL target collection (RECOMMENDED)
deep_interpreter_wrapped_graph = _get_deep_interpreter_graph_wrapped()


__all__ = [
    "create_deep_interpreter_graph",
    "create_deep_interpreter_graph_wrapped",
    "deep_interpreter_graph",
    "deep_interpreter_wrapped_graph",
]
