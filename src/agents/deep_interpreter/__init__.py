"""Deep Interpreter Agent - DeepAgents framework-based CCI interpretation.

This module provides the Deep Interpreter agent for comprehensive Cell-Cell
Interaction (CCI) analysis interpretation using the DeepAgents framework.

Architecture:
- DeepInterpreterWrapperAgent: HITL collection (BaseAgent pattern)
- DeepInterpreterAgent: Core interpreter (DeepAgents create_deep_agent())

Components:
- wrapper_agent.py: Wrapper Agent with HITL for info collection
- wrapper_state.py: Wrapper state schema
- info_extraction.py: Pydantic model for info extraction
- agent.py: Deep Agent using create_deep_agent()
- prompts.py: Orchestrator system prompts
- tools.py: Tool re-exports and think_tool
- subagents/: SubAgent configurations and prompts
- tools/: Analysis tools (data_loader, literature, quality, report)
- skills/: SkillsMiddleware for workflow integration
- graph_builder.py: LangGraph CLI integration

Usage:
    # Wrapped agent with HITL (recommended for interactive use)
    from src.agents.deep_interpreter import deep_interpreter_wrapped_graph

    # Direct Deep Agent (for programmatic use with pre-set targets)
    from src.agents.deep_interpreter import deep_interpreter_graph
"""

from src.agents.deep_interpreter.info_extraction import DeepInterpreterInfoExtraction
from src.agents.deep_interpreter.wrapper_state import (
    DeepInterpreterWrapperState,
    create_initial_state,
)
from src.agents.deep_interpreter.wrapper_agent import DeepInterpreterWrapperAgent
from src.agents.deep_interpreter.agent import (
    DeepInterpreterConfig,
    create_deep_interpreter_agent,
    interpret_analysis,
)
from src.agents.deep_interpreter.graph_builder import (
    create_deep_interpreter_graph,
    create_deep_interpreter_graph_wrapped,
    deep_interpreter_graph,
    deep_interpreter_wrapped_graph,
)

__all__ = [
    # Info extraction
    "DeepInterpreterInfoExtraction",
    # Wrapper state
    "DeepInterpreterWrapperState",
    "create_initial_state",
    # Wrapper agent
    "DeepInterpreterWrapperAgent",
    # Deep agent
    "DeepInterpreterConfig",
    "create_deep_interpreter_agent",
    "interpret_analysis",
    # Graph builders
    "create_deep_interpreter_graph",
    "create_deep_interpreter_graph_wrapped",
    "deep_interpreter_graph",
    "deep_interpreter_wrapped_graph",
]
