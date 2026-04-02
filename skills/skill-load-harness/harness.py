"""Forced-eval skill load harness middleware.

Implements a 3-step forced evaluation protocol (Evaluate → Activate → Implement)
to replace passive skill listing. Injects a structured prompt that forces the LLM
to explicitly evaluate each available skill before proceeding with its task.

Usage:
    harness = SkillLoadHarness(
        skill_registry={"opentargets-database": "skills/opentargets-database"},
    )
    # Add to middleware list when creating a DeepAgent subagent
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import SystemMessage

logger = logging.getLogger(__name__)


class SkillLoadHarness(AgentMiddleware):
    """Middleware that forces explicit skill evaluation before task execution.

    Instead of passively listing skills (SkillsMiddleware, ~20% activation),
    this harness injects a 3-step forced evaluation protocol that requires
    the LLM to explicitly assess each skill's relevance (~84% activation).

    The prompt template is loaded from SKILL.md in the same directory,
    allowing prompt iteration without code changes.

    Args:
        skill_registry: Mapping of skill names to their directory paths.
    """

    def __init__(
        self,
        skill_registry: dict[str, str],
    ) -> None:
        self.skill_registry = skill_registry
        self._prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load the forced-eval prompt template from SKILL.md.

        Extracts the body content after YAML frontmatter.
        """
        skill_md = Path(__file__).parent / "SKILL.md"
        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError:
            logger.warning("SKILL.md not found at %s, using fallback prompt.", skill_md)
            return self._fallback_prompt()

        # Strip YAML frontmatter
        match = re.match(r"^---\n.*?\n---\n(.*)", content, re.DOTALL)
        return match.group(1).strip() if match else content

    @staticmethod
    def _fallback_prompt() -> str:
        """Inline fallback if SKILL.md is missing."""
        return (
            "# Skill Load Harness — Forced Evaluation Protocol\n\n"
            "Before beginning your task, you MUST complete the following 3-step sequence:\n\n"
            "## Step 1 - EVALUATE (mandatory for ALL skills)\n"
            "For each skill listed in {{available_skills}}, explicitly state:\n"
            "- [skill-name] — YES / NO — [one-sentence reasoning]\n\n"
            "**Judgment criteria:**\n"
            "- YES = this skill is **directly required** to complete the current task\n"
            "- NO = this skill is not needed, OR \"might be helpful\" (uncertain = NO)\n"
            "- When in doubt, default to NO. Only mark YES when the task clearly demands it.\n\n"
            "## Step 2 - ACTIVATE (for YES skills only)\n"
            "For each skill marked YES:\n"
            "- Call `read_skill_file(skill_path=\"<path>\")` to load full instructions\n"
            "- Summarize key guidance in 2-3 bullet points\n\n"
            "## Step 3 - IMPLEMENT\n"
            "Proceed with your task. You MUST reference activated skill guidance when making\n"
            "decisions covered by those skills.\n\n"
            "CRITICAL: Do NOT skip Step 1. Evaluate ALL skills. "
            "Step 2 is WORTHLESS without Step 1."
        )

    async def abefore_agent(
        self,
        state: Any,
        runtime: Any,
    ) -> None:
        """No-op: skill_registry is explicit, no scanning needed."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Inject the forced-eval prompt into the system message."""
        # 1. Build the available skills block
        skills_block = self._format_available_skills()

        # 2. Replace {{available_skills}} placeholder in the template
        harness_prompt = self._prompt_template.replace(
            "{{available_skills}}", skills_block
        )

        # 3. Append to existing system prompt
        existing = ""
        if request.system_message:
            existing = str(request.system_message.content)
        elif request.system_prompt:
            existing = request.system_prompt

        enhanced = existing + "\n\n" + harness_prompt if existing else harness_prompt
        modified = request.override(
            system_message=SystemMessage(content=enhanced)
        )
        return await handler(modified)

    def _format_available_skills(self) -> str:
        """Format the skill registry into a readable list for the prompt."""
        if not self.skill_registry:
            return "(No skills registered)"

        lines = []
        for name, path in self.skill_registry.items():
            skill_md = Path(path) / "SKILL.md"
            desc = self._load_skill_description(skill_md)
            lines.append(f"- **{name}**: {desc}\n  Path: `{skill_md}`")
        return "\n".join(lines)

    @staticmethod
    def _load_skill_description(skill_md: Path) -> str:
        """Load the description from a SKILL.md's YAML frontmatter."""
        try:
            content = skill_md.read_text(encoding="utf-8")
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                import yaml

                meta = yaml.safe_load(match.group(1))
                if meta and isinstance(meta, dict):
                    return meta.get("description", "(no description)")
        except Exception:
            pass
        return "(no description)"
