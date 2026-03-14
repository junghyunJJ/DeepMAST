"""Shared progressive-disclosure middleware for agent skills."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import SystemMessage

from src.agents.deep_interpreter.middleware.load import SkillMetadata, list_skills

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    """Find project root by looking for pyproject.toml or .git."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()
SKILLS_DIR = PROJECT_ROOT / "skills"

DEFAULT_USAGE_GUIDANCE = """
**How to Use Skills (Progressive Disclosure):**

1. Identify when a listed skill applies.
2. Read the full skill document using the file-reading tool described in your prompt.
3. Use the normal execution tools after reading the skill guidance.

**Important:**
- Skills provide strategy guidance, not direct execution.
- Do not replace the provided tools with ad hoc file or API access.
"""

SKILLS_SYSTEM_PROMPT = """
## Skills System

You have access to a skills library for specialized workflows.

**Available Skills:**

{skills_list}

{usage_guidance}
"""


class SkillsMiddleware(AgentMiddleware):
    """Inject selected skill metadata into the system prompt."""

    def __init__(
        self,
        *,
        skills_dir: Path | str | None = None,
        allowed_skill_names: Sequence[str] | None = None,
        usage_guidance: str | None = None,
    ) -> None:
        self.skills_dir = Path(skills_dir).expanduser().resolve() if skills_dir else SKILLS_DIR
        self.allowed_skill_names = tuple(allowed_skill_names) if allowed_skill_names else None
        self.usage_guidance = usage_guidance or DEFAULT_USAGE_GUIDANCE
        self._skills_cache: list[SkillMetadata] | None = None

    def _filter_skills(self, skills: list[SkillMetadata]) -> list[SkillMetadata]:
        if not self.allowed_skill_names:
            return skills

        by_name = {skill["name"]: skill for skill in skills}
        return [by_name[name] for name in self.allowed_skill_names if name in by_name]

    def _display_path(self, raw_path: str) -> str:
        path = Path(raw_path)
        try:
            return path.resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return str(path)

    async def abefore_agent(
        self,
        state: Any,
        runtime: Any,
    ) -> None:
        if self._skills_cache is None:
            skills = await asyncio.to_thread(list_skills, project_skills_dir=self.skills_dir)
            self._skills_cache = self._filter_skills(skills)
            if not self._skills_cache:
                logger.warning("No matching skills found in %s.", self.skills_dir)
        return None

    def _format_skills_list(self, skills: list[SkillMetadata]) -> str:
        if not skills:
            return "(No skills available)"

        lines = []
        for skill in skills:
            lines.append(f"- **{skill['name']}**: {skill['description']}")
            lines.append(f"  Path: `{self._display_path(skill['path'])}`")
        return "\n".join(lines)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        skills_metadata = self._skills_cache or []
        skills_section = SKILLS_SYSTEM_PROMPT.format(
            skills_list=self._format_skills_list(skills_metadata),
            usage_guidance=self.usage_guidance.strip(),
        )

        existing_prompt = ""
        if request.system_message:
            existing_prompt = str(request.system_message.content)
        elif request.system_prompt:
            existing_prompt = request.system_prompt

        enhanced_prompt = (
            existing_prompt + "\n\n" + skills_section if existing_prompt else skills_section
        )
        modified_request = request.override(
            system_message=SystemMessage(content=enhanced_prompt)
        )
        return await handler(modified_request)
