"""Middleware components for Deep Interpreter Agent.

This module provides middleware for enhancing the Deep Interpreter with:
- SkillsMiddleware: Progressive Disclosure pattern for skill management
- Skill loader for project skills directory

Architecture:
    SkillsMiddleware (Strategy Layer) → Python Tools (Execution Layer) → MCP Servers
"""

from src.agents.deep_interpreter.middleware.skills_middleware import SkillsMiddleware
from src.agents.deep_interpreter.middleware.write_file_guard import WriteFileArgGuardMiddleware
from src.agents.deep_interpreter.middleware.load import list_skills, SkillMetadata
from src.agents.deep_interpreter.middleware.report_guardrail import ReportGuardrailMiddleware
from src.agents.deep_interpreter.reporter_recovery import ReporterTaskRecoveryMiddleware

__all__ = [
    "ReportGuardrailMiddleware",
    "ReporterTaskRecoveryMiddleware",
    "SkillsMiddleware",
    "WriteFileArgGuardMiddleware",
    "list_skills",
    "SkillMetadata",
]
