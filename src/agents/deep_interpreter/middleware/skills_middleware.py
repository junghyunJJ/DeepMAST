"""Custom SkillsMiddleware for Deep Interpreter Agent.

This middleware implements Progressive Disclosure for skill management:
- Session start: Load skill metadata only (name, description, path)
- System prompt: Inject skill list with paths
- On demand: Agent reads full SKILL.md when needed

Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │              SkillsMiddleware (Strategy Layer)                   │
    │  skills/biomedical-literature-search/SKILL.md → search strategies│
    │  - Progressive Disclosure: metadata only, full content on demand │
    │  - System prompt: skill list + usage instructions                │
    └─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                    Python Tools (Execution Layer)                │
    │  tools/literature.py → stable MCP calls + error handling        │
    └─────────────────────────────────────────────────────────────────┘
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Awaitable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import SystemMessage

from src.agents.deep_interpreter.middleware.load import SkillMetadata, list_skills

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    """Find project root — delegates to shared utility."""
    from src.agents.shared.utils import find_project_root
    return find_project_root()


# Project root and skills directory
PROJECT_ROOT = _find_project_root()
SKILLS_DIR = PROJECT_ROOT / "skills"

SKILLS_SYSTEM_PROMPT = """
## Skills System

You have access to a skills library for specialized workflows.

**Available Skills:**

{skills_list}

**How to Use Skills (Progressive Disclosure):**

1. **Identify when a skill applies**: Check if your task matches a skill's description.
2. **Read the skill's full instructions**: Use read_file tool with the path shown above.
3. **Follow the skill's workflow**: SKILL.md contains step-by-step instructions.

**When to use skills:**
- When performing literature search for CCI interpretation
- When specialized knowledge or structured workflows would help
- When you need search strategies for different analysis types (L-R, pathway, gene/marker)

**Important:**
- Skills provide *strategy guidance*, not direct tool execution
- After reading a skill, use the appropriate Python tools (search_literature_dynamic, search_literature)
- The skill file explains WHEN and HOW to search, the tools execute the search
"""


class SkillsMiddleware(AgentMiddleware):
    """Custom SkillsMiddleware for Deep Interpreter Agent.

    Implements Progressive Disclosure pattern for skill management:
    - Session start: Load only skill metadata (name, description, path)
    - System prompt: Inject skill list with instructions
    - On demand: Agent reads full SKILL.md when needed via read_file

    This hybrid architecture separates:
    - Strategy (skills): When/how to search, quality criteria, iteration limits
    - Execution (tools): Stable MCP calls with error handling

    Usage:
        >>> middleware = SkillsMiddleware()
        >>> agent = create_deep_agent(
        ...     model=llm,
        ...     middleware=[middleware],
        ...     ...
        ... )

    Attributes:
        skills_dir: Path to project skills directory
        _skills_cache: Cached skill metadata (loaded once per session)
    """

    def __init__(self, *, skills_dir: Path | None = None) -> None:
        """Initialize SkillsMiddleware.

        Args:
            skills_dir: Path to skills directory. Defaults to {PROJECT_ROOT}/skills/
        """
        self.skills_dir = skills_dir or SKILLS_DIR
        self._skills_cache: list[SkillMetadata] | None = None

    async def abefore_agent(
        self,
        state: Any,
        runtime: Any,
    ) -> None:
        """Load skill metadata before agent execution.

        Called once at the start of agent execution. Loads skill metadata
        from the project skills directory and caches it for use in
        awrap_model_call (where it's injected into the system prompt).

        Note: We don't return state updates here because skills_metadata
        may not be in the state schema. Instead, we cache the metadata
        and inject it via awrap_model_call.

        Args:
            state: Current agent state
            runtime: Agent runtime context
        """
        if self._skills_cache is None:
            self._skills_cache = await asyncio.to_thread(
                list_skills, project_skills_dir=self.skills_dir
            )
            if not self._skills_cache:
                logger.warning(
                    "No skills found in %s. "
                    "SEARCHER may lack workflow guidance.",
                    self.skills_dir,
                )
        return None

    def _format_skills_list(self, skills: list[SkillMetadata]) -> str:
        """Format skill metadata as a readable list for system prompt.

        Args:
            skills: List of skill metadata dictionaries

        Returns:
            Formatted string with skill names, descriptions, and paths
        """
        if not skills:
            return "(No skills available)"

        lines = []
        for skill in skills:
            lines.append(f"- **{skill['name']}**: {skill['description']}")
            lines.append(f"  Path: `{skill['path']}`")
        return "\n".join(lines)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Wrap model calls to inject skills information into system prompt.

        Enhances the system prompt with available skills list and usage
        instructions. This enables the agent to discover and use skills
        without explicit tool calls.

        Args:
            request: The model request containing messages and config
            handler: The next handler in the middleware chain

        Returns:
            Model response from the handler
        """
        # Use cached skills metadata (loaded in abefore_agent)
        skills_metadata: list[SkillMetadata] = self._skills_cache or []

        # Format skills list
        skills_list = self._format_skills_list(skills_metadata)
        skills_section = SKILLS_SYSTEM_PROMPT.format(skills_list=skills_list)

        # Build enhanced system prompt
        existing_prompt = ""
        if request.system_message:
            existing_prompt = str(request.system_message.content)
        elif request.system_prompt:
            existing_prompt = request.system_prompt

        if existing_prompt:
            enhanced_prompt = existing_prompt + "\n\n" + skills_section
        else:
            enhanced_prompt = skills_section

        # Create modified request with enhanced system prompt
        modified_request = request.override(
            system_message=SystemMessage(content=enhanced_prompt)
        )

        return await handler(modified_request)
