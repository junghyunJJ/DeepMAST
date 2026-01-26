"""Deep Interpreter Agent using DeepAgents framework.

This module implements the main Deep Interpreter agent using create_deep_agent()
with 11 specialized subagents for comprehensive CCI analysis interpretation.

Architecture:
- Main orchestrator: create_deep_agent() with HITL support
- Subagents: 11 specialized agents for different interpretation phases
  - 1 CompiledSubAgent (literature-searcher with BioMCP workflow)
  - 10 Simple SubAgents
- Middleware: FilesystemMiddleware, TodoListMiddleware, SummarizationMiddleware
- Backend: CompositeBackend with FilesystemBackend for persistent file storage

Note on HITL behavior:
- Deep Agents' interrupt_on only works on tool names, not subagent names
- For HITL with target selection:
  1. Wrapper agent collects targets from user
  2. Wrapper passes targets to Deep Agent via initial message
  3. target-selector (readonly) parses and writes /targets.json
  4. Strategic planning and interpretation proceed without HITL

Backend Configuration:
- Workspace location: Dynamic based on user's data_dir
- Virtual mode: Enabled (files stored in-memory, flushed on completion)
- Backend sharing: Orchestrator and CompiledSubAgent share same filesystem
"""

import uuid
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional, Sequence

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from langchain.tools import ToolRuntime
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver

from src.agents.model import create_llm
from src.agents.deep_interpreter.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from src.agents.deep_interpreter.subagents.configs import get_subagents
from src.agents.deep_interpreter.subagents.literature_searcher.agent import (
    get_literature_searcher_config,
)
from src.agents.deep_interpreter.tools import (
    load_analysis_data,
    search_literature,
    search_literature_for_context,
    validate_quality,
    validate_claim_literature,
    generate_html_report,
    think_tool,
)


@dataclass
class DeepInterpreterConfig:
    """Configuration for Deep Interpreter Agent.

    Attributes:
        provider: LLM provider ('openai', 'google', 'ollama').
                  Uses LLM_PROVIDER env var if not specified.
        data_dir: Directory for CCI analysis results and agent workspace
        max_iterations: Maximum quality refinement iterations per part (default: 3)
        quality_threshold: Minimum quality score to pass (default: 0.7)
        use_checkpointer: Whether to use memory checkpointer (default: False)
        virtual_mode: If True, files stored in-memory first, flushed on completion
        max_file_size_mb: Maximum file size for filesystem backend (default: 20MB)
        custom_tools: Additional tools to include
        custom_subagents: Additional subagents to include
        output_dir: Output directory for reports (default: current directory)

    Note:
        Model name is determined by environment variables:
        - OPENAI_MODEL (default: gpt-4.1-mini)
        - GOOGLE_MODEL (default: gemini-2.0-flash)
        - OLLAMA_MODEL (default: gpt-oss:20b)
    """
    provider: Literal["openai", "google", "ollama"] = "openai"
    data_dir: str = "/tmp/deep_interpreter_workspace"
    max_iterations: int = 3
    quality_threshold: float = 0.7
    use_checkpointer: bool = False  # Requires thread_id in config when True
    virtual_mode: bool = True
    max_file_size_mb: int = 20
    custom_tools: Sequence[BaseTool] = field(default_factory=list)
    custom_subagents: list[dict] = field(default_factory=list)
    output_dir: str = "."


def _create_backend_factory(
    config: DeepInterpreterConfig,
) -> tuple[Callable[[ToolRuntime], CompositeBackend], FilesystemBackend]:
    """Create backend factory for Deep Interpreter.

    Creates a CompositeBackend factory that:
    - Uses StateBackend for in-memory state management
    - Routes file operations to FilesystemBackend based on config.data_dir

    Args:
        config: Deep Interpreter configuration

    Returns:
        Tuple of (backend_factory function, fs_backend instance)
        The fs_backend is returned for sharing with subagents
    """
    fs_backend = FilesystemBackend(
        root_dir=config.data_dir,
        virtual_mode=config.virtual_mode,
        max_file_size_mb=config.max_file_size_mb,
    )

    def backend_factory(rt: ToolRuntime) -> CompositeBackend:
        """Factory function that creates CompositeBackend for runtime."""
        return CompositeBackend(
            default=StateBackend(rt),
            routes={"/": fs_backend},
        )

    return backend_factory, fs_backend


def create_deep_interpreter_agent(
    config: Optional[DeepInterpreterConfig] = None,
) -> Runnable:
    """Create the Deep Interpreter agent using DeepAgents framework.

    This function creates a fully configured Deep Interpreter agent with:
    - 11 specialized subagents (1 CompiledSubAgent, 10 Simple)
    - Memory checkpointing for conversation persistence
    - FilesystemMiddleware for context management
    - CompositeBackend with FilesystemBackend for persistent file storage

    Args:
        config: Optional configuration object. Uses defaults if not provided.

    Returns:
        Compiled Deep Agent runnable
    """
    if config is None:
        config = DeepInterpreterConfig()

    # Create LLM using the unified model factory
    # Respects environment variables: LLM_PROVIDER, OPENAI_MODEL, GOOGLE_MODEL, OLLAMA_MODEL
    llm = create_llm(provider=config.provider)

    # Create backend factory for file system operations
    # Backend is shared between orchestrator and CompiledSubAgent (literature-searcher)
    backend_factory, _fs_backend = _create_backend_factory(config)

    # Build tools list (includes hybrid workflow tools)
    tools = [
        load_analysis_data,
        search_literature,
        search_literature_for_context,  # Proactive search for context
        validate_quality,
        validate_claim_literature,  # Claim-literature alignment validation
        generate_html_report,
        think_tool,  # Quality validation with reflection
    ]

    # Add custom tools
    if config.custom_tools:
        tools.extend(config.custom_tools)

    # Get Simple subagent configurations (excludes literature-searcher)
    subagents = get_subagents(
        custom_tools=config.custom_tools,
        exclude_literature_searcher=True,
    )

    # Add literature-searcher as CompiledSubAgent with shared backend
    literature_searcher_config = get_literature_searcher_config(
        llm=llm,
        backend=backend_factory,
    )
    subagents.append(literature_searcher_config)

    # Add custom subagents
    if config.custom_subagents:
        subagents.extend(config.custom_subagents)

    # Configure checkpointer
    # LangGraph API handles persistence automatically, so None is used for deployment
    # MemorySaver is only used for standalone/testing scenarios
    checkpointer = MemorySaver() if config.use_checkpointer else None

    # HITL Note: interrupt_on only works on tool names at the main agent level,
    # not on subagent names. HITL is handled by the wrapper agent.
    interrupt_on = {}

    # Create the agent with backend factory
    agent = create_deep_agent(
        model=llm,
        tools=tools,
        subagents=subagents,
        checkpointer=checkpointer,
        interrupt_on=interrupt_on,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        backend=backend_factory,
    )

    return agent


def create_deep_interpreter_graph():
    """Create Deep Interpreter graph for LangGraph deployment.

    This function is used by the graph_builder.py for LangGraph CLI integration.

    Returns:
        Compiled Deep Agent graph
    """
    config = DeepInterpreterConfig()
    return create_deep_interpreter_agent(config)


# Convenience function for quick usage
def interpret_analysis(
    data_dir: str = '/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res',
    analysis_mode: str = "cluster_to_celltype",
    targets: Optional[list[str]] = None,
    output_path: Optional[str] = None,
    provider: Literal["openai", "google", "ollama"] = "ollama",
    thread_id: Optional[str] = None,
    use_checkpointer: bool = False,
) -> dict:
    """Convenience function to interpret CCI analysis results.

    This is a simplified interface for common usage patterns.
    Note: This bypasses the wrapper agent and directly invokes the Deep Agent.
    For interactive HITL target selection, use the wrapper agent instead.

    Args:
        data_dir: Path to directory containing CCI analysis results
        analysis_mode: 'cluster_to_celltype' (Mode A) or 'celltype_to_cluster' (Mode B)
        targets: List of cluster IDs (Mode A) or cell type names (Mode B)
        output_path: Output path for HTML report (default: {data_dir}/CCI_Analysis_Report.html)
        provider: LLM provider ('openai', 'google', 'ollama')
        thread_id: Optional thread ID for checkpointer. Auto-generated if not provided.
        use_checkpointer: Whether to use memory checkpointer (default: False)

    Returns:
        Dictionary with interpretation results, report path, and thread_id
    """
    import json

    if output_path is None:
        output_path = f"{data_dir}/CCI_Analysis_Report.html"

    if targets is None:
        targets = []

    config = DeepInterpreterConfig(
        provider=provider,
        data_dir=data_dir,
        output_dir=data_dir,
        use_checkpointer=use_checkpointer,
    )

    agent = create_deep_interpreter_agent(config)

    # Build targets content
    targets_content = {
        "analysis_mode": analysis_mode,
        "interest_clusters": targets if analysis_mode == "cluster_to_celltype" else None,
        "interest_celltypes": targets if analysis_mode == "celltype_to_cluster" else None,
        "data_directory": data_dir,
        "user_confirmed": True,
    }

    # Build initial message with embedded targets
    initial_message = f"""Interpret the CCI analysis results in {data_dir}.

## PRE-SELECTED TARGET CONFIGURATION
The following targets have been pre-selected (DO NOT ask for user input):

```json
{json.dumps(targets_content, indent=2)}
```

Generate a comprehensive interpretation report to {output_path}."""

    # Build invoke config with thread_id if checkpointer is enabled
    invoke_config = {}
    if use_checkpointer:
        invoke_config["configurable"] = {
            "thread_id": thread_id or str(uuid.uuid4())
        }

    # Run the interpretation
    result = agent.invoke(
        {
            "messages": [{
                "role": "user",
                "content": initial_message,
            }]
        },
        config=invoke_config if invoke_config else None,
    )

    return {
        "messages": result.get("messages", []),
        "files": result.get("files", {}),
        "output_path": output_path,
        "thread_id": invoke_config.get("configurable", {}).get("thread_id"),
    }


# Export for module-level access
__all__ = [
    "create_deep_interpreter_agent",
    "create_deep_interpreter_graph",
    "interpret_analysis",
    "DeepInterpreterConfig",
]
