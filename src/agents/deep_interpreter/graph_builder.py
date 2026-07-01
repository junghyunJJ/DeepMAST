"""Graph builder for Deep Interpreter Agent.

This module provides the graph builder function for LangGraph CLI integration.
The Deep Interpreter uses the DeepAgents framework (create_deep_agent).

Graph variants available:
1. deep_interpreter_graph: Deep Agent with pre-selected targets (no HITL in agent)
2. deep_interpreter_wrapped_graph: Wrapper agent with HITL target collection (recommended)
3. interpreter_subagent_graph: Standalone INTERPRETER subagent for testing (NEW)
"""

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from langchain_core.runnables import Runnable
from langgraph.prebuilt import create_react_agent

# Load .env file before any os.getenv() calls
# This ensures environment variables are available at module import time
load_dotenv()

from src.agents.deep_interpreter.agent import (  # noqa: E402
    create_deep_interpreter_agent,
    DeepInterpreterConfig,
)
from src.agents.deep_interpreter.wrapper_agent import (  # noqa: E402
    DeepInterpreterWrapperAgent,
)
from src.agents.model import create_llm  # noqa: E402


def create_deep_interpreter_graph(
    provider: Literal["openai", "google", "ollama", "ollama-openai", "vllm", "claude", "openrouter"] = "ollama",
    data_dir: str = "",
    use_checkpointer: bool = True,
    is_debug: bool = False,
) -> Runnable:
    """Create Deep Interpreter graph for LangGraph deployment.

    The Deep Interpreter uses the DeepAgents framework which provides:
    - FilesystemMiddleware for context management
    - TodoListMiddleware for task tracking
    - SubAgentMiddleware for specialized subagents (4 subagents: planner, searcher, interpreter, reporter)
    - Reflection/quality policy (per-subagent):
        * INTERPRETER: think_tool and validate_quality(use_llm=False) are advisory only;
          downstream report validation/repair owns hard report-level guardrails.
        * REPORTER:    think_tool x3 strategic-planning passes + think_tool quality reflection are
          prompt-mandatory (soft); validate_quality is secondary/non-gating.
        * SEARCHER:    reflection-free; guarded by tests/deep_interpreter/test_searcher_reflection_policy.py.
    - CompositeBackend with FilesystemBackend for persistent file storage

    NOTE: This variant expects targets to be pre-selected. For interactive
    target selection, use deep_interpreter_wrapped_graph instead.

    Args:
        provider: LLM provider ('openai', 'google', 'ollama')
        data_dir: Directory for CCI analysis results and agent workspace.
                  Falls back to DEEP_INTERPRETER_DATA_DIR env var, then /tmp/deep_interpreter_workspace.
        use_checkpointer: Whether to use memory checkpointer
        is_debug: Enable debug mode

    Returns:
        Compiled Deep Agent runnable
    """
    if not data_dir:
        data_dir = os.getenv("DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace")

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

    Uses environment variables:
    - LLM_PROVIDER: LLM provider (default: "openai")

    Returns:
        Compiled Deep Agent runnable
    """
    provider = os.getenv("LLM_PROVIDER", "openai")
    data_dir = os.getenv("DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace")
    return create_deep_interpreter_graph(
        provider=provider,
        data_dir=data_dir,
        use_checkpointer=False,  # LangGraph CLI uses its own persistence
        is_debug=False,
    )


def create_deep_interpreter_graph_wrapped(
    provider: Literal["openai", "google", "ollama", "ollama-openai", "vllm", "claude", "openrouter"] = "ollama",
    data_dir: str = "",
    use_checkpointer: bool = False,
    is_debug: bool = False,
    subagent_models: dict[str, str] | None = None,
) -> Runnable:
    """Create wrapped Deep Interpreter graph with HITL target collection.

    This variant uses the wrapper agent pattern where:
    1. Wrapper collects h5ad_files, cluster_key, data_directory from user (HITL)
    2. Wrapper executes spatial analysis Steps 1-8 via MCP
    3. Wrapper runs HITL research discussion (interest_clusters, celltypes, factor)
    4. Wrapper executes targeted analysis Steps 9-11 via MCP
    5. Wrapper invokes Deep Agent for interpretation/report generation

    This is the RECOMMENDED variant for interactive use.

    Note: The data_dir can be provided as a default, but the wrapper agent
    may override it with the user-provided data_directory during HITL.

    Args:
        provider: LLM provider ('openai', 'google', 'ollama')
        data_dir: Default directory for CCI analysis results and agent workspace.
                  Falls back to DEEP_INTERPRETER_DATA_DIR env var, then /tmp/deep_interpreter_workspace.
        use_checkpointer: Whether to use memory checkpointer
        is_debug: Enable debug mode

    Returns:
        Compiled Wrapper Agent runnable
    """
    if not data_dir:
        data_dir = os.getenv("DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace")
    # Create LLM using the model factory (uses environment variables)
    llm = create_llm(provider=provider)

    # Create Deep Agent config for the wrapped version
    # Note: data_dir may be overridden by wrapper based on user input
    deep_agent_config = DeepInterpreterConfig(
        provider=provider,
        data_dir=data_dir,
        use_checkpointer=use_checkpointer,
        subagent_models=subagent_models,
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

    Uses environment variables:
    - LLM_PROVIDER: LLM provider (default: "openai")
    Note: Wrapper overrides data_dir with user-provided path during HITL.

    Returns:
        Compiled Wrapper Agent runnable
    """
    provider = os.getenv("LLM_PROVIDER", "openai")
    data_dir = os.getenv("DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace")
    return create_deep_interpreter_graph_wrapped(
        provider=provider,
        data_dir=data_dir,
        use_checkpointer=False,  # LangGraph CLI uses its own persistence
        is_debug=False,
    )


# LangGraph CLI exports
# Deep Agent (expects pre-selected targets)
deep_interpreter_graph = _get_deep_interpreter_graph()

# Wrapped version with HITL target collection (RECOMMENDED)
deep_interpreter_wrapped_graph = _get_deep_interpreter_graph_wrapped()


# =============================================================================
# Standalone Subagent Graphs (for testing individual subagents)
# =============================================================================
# Each subagent can be run independently via `langgraph dev` for testing.
# Workflow order: PLANNER → SEARCHER → INTERPRETER → REPORTER
# =============================================================================


def create_subagent_graph(
    subagent_name: Literal["planner", "searcher", "interpreter", "reporter"],
    provider: Literal["openai", "google", "ollama", "ollama-openai", "vllm", "claude", "openrouter"] = "openai",
) -> Runnable:
    """Create standalone subagent graph for testing.

    This creates a React agent using the specified subagent configuration,
    allowing you to test each subagent independently via `langgraph dev`.

    Subagent Descriptions:
    - **planner**: Target confirmation + data assessment + interpretation guide
      - Reads /targets.json, loads analysis data
      - Outputs: /interpretation_guide.md, /data_path.txt

    - **searcher**: Context extraction + unified literature search
      - Outputs /papers.json (shared by all Parts)
      - Uses search_literature_dynamic with automatic fallback

    - **interpreter**: Literature-grounded interpretation
      - Reads /papers.json (ONLY citation source)
      - Validates claims; quality checks are advisory, not numeric retry gates
      - Outputs: /part1_final.md, /part2_final.md, /part3_final.md

    - **reporter**: Cross-part synthesis + HTML report
      - Reads all /partN_final.md files
      - Outputs: /synthesis.md, CCI_Analysis_Report.html

    Args:
        subagent_name: Name of the subagent
        provider: LLM provider ('openai', 'google', 'ollama', 'claude')

    Returns:
        Compiled React Agent runnable for the specified subagent
    """
    from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS
    from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS
    from src.agents.deep_interpreter.tools.standalone_fs import write_file, read_file

    # Ensure DEEP_INTERPRETER_DATA_DIR is absolute for tool fallback.
    # In embedded mode, agent.py:182 normalizes this. In standalone mode, we must do it here.
    _standalone_data_dir = os.getenv("DEEP_INTERPRETER_DATA_DIR", "")
    if _standalone_data_dir:
        os.environ["DEEP_INTERPRETER_DATA_DIR"] = str(Path(_standalone_data_dir).expanduser().resolve())
    else:
        import warnings
        warnings.warn(
            "DEEP_INTERPRETER_DATA_DIR not set. Standalone subagent will use "
            "/tmp/deep_interpreter_workspace. Set this in .env for proper file resolution.",
            UserWarning, stacklevel=2,
        )

    # Get subagent config
    config = SUBAGENT_CONFIGS[subagent_name]

    # Create LLM
    llm = create_llm(provider=provider)

    # Get tools from config + standalone filesystem tools
    # (In embedded mode, FilesystemMiddleware injects these; standalone needs them explicitly)
    tools = list(config["tools"]) + [write_file, read_file]

    # Get system prompt
    system_prompt = SUBAGENT_PROMPTS[subagent_name]

    # Create React agent with subagent config
    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=system_prompt,
    )

    # Apply per-subagent recursion limits.
    # The default recursion_limit=25 from langchain_core is too low for
    # standalone subagent graphs (e.g., reporter needs ~70-90 node transitions).
    # Production path (full pipeline) uses SubAgentMiddleware which sets 10,000.
    SUBAGENT_RECURSION_LIMITS = {
        "planner": 100,
        "searcher": 150,
        "interpreter": 200,
        "reporter": 200,
    }
    limit = SUBAGENT_RECURSION_LIMITS.get(subagent_name, 100)
    return agent.with_config({"recursion_limit": limit})


# -----------------------------------------------------------------------------
# PLANNER Subagent
# -----------------------------------------------------------------------------
def _get_planner_subagent_graph() -> Runnable:
    """Standalone PLANNER subagent graph - for LangGraph CLI."""
    provider = os.getenv("LLM_PROVIDER", "openai")
    return create_subagent_graph("planner", provider=provider)


planner_subagent_graph = _get_planner_subagent_graph()


# -----------------------------------------------------------------------------
# SEARCHER Subagent
# -----------------------------------------------------------------------------
def _get_searcher_subagent_graph() -> Runnable:
    """Standalone SEARCHER subagent graph - for LangGraph CLI."""
    provider = os.getenv("LLM_PROVIDER", "openai")
    return create_subagent_graph("searcher", provider=provider)


searcher_subagent_graph = _get_searcher_subagent_graph()


# -----------------------------------------------------------------------------
# INTERPRETER Subagent
# -----------------------------------------------------------------------------
def _get_interpreter_subagent_graph() -> Runnable:
    """Standalone INTERPRETER subagent graph - for LangGraph CLI."""
    provider = os.getenv("LLM_PROVIDER", "openai")
    return create_subagent_graph("interpreter", provider=provider)


interpreter_subagent_graph = _get_interpreter_subagent_graph()


# -----------------------------------------------------------------------------
# REPORTER Subagent
# -----------------------------------------------------------------------------
def _get_reporter_subagent_graph() -> Runnable:
    """Standalone REPORTER subagent graph - for LangGraph CLI."""
    provider = os.getenv("LLM_PROVIDER", "openai")
    return create_subagent_graph("reporter", provider=provider)


reporter_subagent_graph = _get_reporter_subagent_graph()


__all__ = [
    # Main graphs
    "create_deep_interpreter_graph",
    "create_deep_interpreter_graph_wrapped",
    "deep_interpreter_graph",
    "deep_interpreter_wrapped_graph",
    # Subagent factory
    "create_subagent_graph",
    # Individual subagent graphs
    "planner_subagent_graph",
    "searcher_subagent_graph",
    "interpreter_subagent_graph",
    "reporter_subagent_graph",
]
