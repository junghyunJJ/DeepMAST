"""SubAgent configurations for Deep Interpreter Agent.

Simplified 4-Agent Architecture:
- PLANNER: Target confirmation + hypothesis generation
- SEARCHER: Context extraction + literature search
- INTERPRETER: Part 1/2/3 interpretation with inline validation
- REPORTER: Cross-part synthesis + HTML report generation

This module provides the subagent definitions used by create_deep_agent().
"""

from src.agents.deep_interpreter.subagents.configs import (
    get_subagents,
    get_subagent_by_name,
    get_simplified_subagents,
    SUBAGENT_CONFIGS,
    WORKFLOW_ORDER,
    WORKFLOW_DESCRIPTION,
)
from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS

__all__ = [
    # Config functions
    "get_subagents",
    "get_subagent_by_name",
    "get_simplified_subagents",
    # Config constants
    "SUBAGENT_CONFIGS",
    "WORKFLOW_ORDER",
    "WORKFLOW_DESCRIPTION",
    # Prompts
    "SUBAGENT_PROMPTS",
]
