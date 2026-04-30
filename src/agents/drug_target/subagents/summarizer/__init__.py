"""Summarizer CompiledSubAgent for Drug Target report finalization."""

from src.agents.drug_target.subagents.summarizer.agent import (
    create_summarizer_agent,
    get_summarizer_subagent,
    wrap_summarizer_with_critic_slices,
)

__all__ = [
    "create_summarizer_agent",
    "get_summarizer_subagent",
    "wrap_summarizer_with_critic_slices",
]
