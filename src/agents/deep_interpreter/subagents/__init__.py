"""SubAgent configurations for Deep Interpreter Agent.

This module provides the subagent definitions used by create_deep_agent().
"""

from src.agents.deep_interpreter.subagents.configs import (
    get_subagents,
    get_subagent_by_name,
    get_interpretation_subagents,
    get_workflow_subagents,
    get_hybrid_workflow_subagents,
)
from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS

__all__ = [
    "get_subagents",
    "get_subagent_by_name",
    "get_interpretation_subagents",
    "get_workflow_subagents",
    "get_hybrid_workflow_subagents",
    "SUBAGENT_PROMPTS",
]
