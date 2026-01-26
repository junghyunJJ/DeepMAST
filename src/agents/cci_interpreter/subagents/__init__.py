"""Subagent configurations for CCI Interpreter Agent.

This module provides subagent definitions and configurations for the
Deep Agents-based CCI Interpreter.
"""

from src.agents.cci_interpreter.subagents.configs import (
    get_hybrid_workflow_subagents,
    get_interpretation_subagents,
    get_subagent_by_name,
    get_subagents,
    get_workflow_subagents,
)
from src.agents.cci_interpreter.subagents.prompts import SUBAGENT_PROMPTS

__all__ = [
    "get_subagents",
    "get_subagent_by_name",
    "get_interpretation_subagents",
    "get_workflow_subagents",
    "get_hybrid_workflow_subagents",
    "SUBAGENT_PROMPTS",
]
