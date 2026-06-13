"""Shared Skill Activation Governor middleware."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import SystemMessage


class SkillActivationGovernor(AgentMiddleware):
    """Inject the skill-activation-governor protocol into agent model calls."""

    def __init__(
        self,
        *,
        skill_registry: dict[str, str],
        required_skill_names: Sequence[str] | None = None,
        hard_required_skill_names: Sequence[str] | None = None,
        candidate_skill_names: Sequence[str] | None = None,
        artifact_gate: str = "final artifact",
    ) -> None:
        self.skill_registry = dict(skill_registry)
        if hard_required_skill_names is None and required_skill_names is not None:
            hard_required_skill_names = required_skill_names
        self.hard_required_skill_names = tuple(hard_required_skill_names or ())
        self.required_skill_names = self.hard_required_skill_names
        hard_required_set = set(self.hard_required_skill_names)
        self.candidate_skill_names = tuple(
            candidate_skill_names
            if candidate_skill_names is not None
            else (
                name
                for name in self.skill_registry
                if name not in hard_required_set
            )
        )
        self.artifact_gate = artifact_gate
        self._prompt_template = self._load_prompt_template()

    async def abefore_agent(
        self,
        state: Any,
        runtime: Any,
    ) -> None:
        """No-op: activation context is explicit."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Inject the Governor protocol into the system message."""
        existing = ""
        if request.system_message:
            existing = str(request.system_message.content)
        elif request.system_prompt:
            existing = request.system_prompt

        hard_required = (
            ", ".join(self.hard_required_skill_names)
            if self.hard_required_skill_names
            else "NONE"
        )
        required_alias = (
            ", ".join(self.required_skill_names)
            if self.required_skill_names
            else "NONE"
        )
        candidates = (
            ", ".join(self.candidate_skill_names)
            if self.candidate_skill_names
            else "NONE"
        )
        available = ", ".join(self.skill_registry) if self.skill_registry else "NONE"
        required_context = (
            "Required skills are provided by this caller. Treat the list below "
            "as authoritative and complete coverage before the artifact gate."
            if self.hard_required_skill_names
            else (
                "No `required_skill_names` are provided by this caller. Use the "
                "governor's flexible discovery path only: evaluate the available "
                "skills below, activate directly relevant skills with "
                "`read_skill_file`, and do not invent a deterministic required list."
            )
        )
        governor_prompt = "\n\n".join(
            [
                self._prompt_template,
                "## Runtime Activation Context",
                f"Hard required skills: {hard_required}",
                f"Required skills: {required_alias}",
                f"Candidate skills: {candidates}",
                f"Available skills: {available}",
                f"Artifact gate: {self.artifact_gate}",
                "Evaluate every candidate skill with YES or NO.",
                "NO candidates must remain suppressed.",
                required_context,
                "## Available Skills for Flexible Discovery",
                self._format_available_skills(),
            ]
        )
        enhanced = existing + "\n\n" + governor_prompt if existing else governor_prompt
        modified = request.override(system_message=SystemMessage(content=enhanced))
        return await handler(modified)

    @staticmethod
    def _load_prompt_template() -> str:
        """Load the Governor protocol from skills/skill-activation-governor."""
        skill_md = (
            Path(__file__).resolve().parents[3]
            / "skills"
            / "skill-activation-governor"
            / "SKILL.md"
        )
        content = skill_md.read_text(encoding="utf-8")
        match = re.match(r"^---\n.*?\n---\n(.*)", content, re.DOTALL)
        return match.group(1).strip() if match else content.strip()

    def _format_available_skills(self) -> str:
        """Format the skill registry into a readable list for the prompt."""
        lines: list[str] = []
        for name, path in self.skill_registry.items():
            skill_md = Path(path) / "SKILL.md"
            description = self._load_skill_description(skill_md)
            lines.append(f"- **{name}**: {description}\n  Path: `{skill_md}`")
        return "\n".join(lines) if lines else "(No skills registered)"

    @staticmethod
    def _load_skill_description(skill_md: Path) -> str:
        """Load the description from a SKILL.md's YAML frontmatter."""
        try:
            content = skill_md.read_text(encoding="utf-8")
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                import yaml

                meta = yaml.safe_load(match.group(1))
                if isinstance(meta, dict):
                    return str(meta.get("description") or "(no description)")
        except Exception:
            return "(no description)"
        return "(no description)"
