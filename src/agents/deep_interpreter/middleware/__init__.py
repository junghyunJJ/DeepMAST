"""Middleware components for Deep Interpreter Agent.

This module provides middleware for enhancing the Deep Interpreter with:
- SkillsMiddleware: Progressive Disclosure pattern for skill management
- Skill loader for project skills directory

Architecture:
    SkillsMiddleware (Strategy Layer) → Python Tools (Execution Layer) → MCP Servers
"""

from src.agents.deep_interpreter.middleware.skills import SkillsMiddleware
from src.agents.deep_interpreter.middleware.load import list_skills, SkillMetadata

__all__ = [
    "SkillsMiddleware",
    "list_skills",
    "SkillMetadata",
]
