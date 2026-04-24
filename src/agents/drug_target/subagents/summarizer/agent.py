"""Summarizer CompiledSubAgent for audited drug target report finalization."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.protocol import BackendFactory, BackendProtocol
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from src.agents.deep_interpreter.middleware.write_file_guard import (
    ReadOnlyToolGuardMiddleware,
)
from src.agents.drug_target.subagents.prompts import SUMMARIZER_PROMPT
from src.agents.drug_target.tools import (
    think_tool,
    validate_drug_md,
    validate_quality,
    validate_stage3_gate,
)

_SUMMARIZER_BLOCKED_TOOLS = (
    "save_drug_md",
    "save_target_assessment",
    "save_evidence",
)


def create_summarizer_agent(
    *,
    model: str | BaseChatModel | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    inner_subagents: Sequence[dict[str, Any]] = (),
    tools: Sequence[BaseTool | Any] | None = None,
) -> Runnable:
    """Create the autonomous report-finalization DeepAgent.

    The summarizer supervises the write -> validate -> critic -> repair loop.
    It is intentionally not an artifact writer; only its inner report_writer
    subagent owns drug.md and target_assessment.json writes.
    """
    summarizer_tools = list(tools or [
        validate_drug_md,
        validate_quality,
        validate_stage3_gate,
        think_tool,
    ])

    agent = create_deep_agent(
        model=model,
        tools=summarizer_tools,
        system_prompt=SUMMARIZER_PROMPT,
        subagents=list(inner_subagents),
        backend=backend,
        middleware=[
            ReadOnlyToolGuardMiddleware(
                blocked_tool_names=_SUMMARIZER_BLOCKED_TOOLS,
            )
        ],
    )

    return agent.with_config({"recursion_limit": 3000})


def get_summarizer_subagent(
    *,
    model: str | BaseChatModel | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    inner_subagents: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Return the summarizer in DeepAgents CompiledSubAgent format."""
    agent = create_summarizer_agent(
        model=model,
        backend=backend,
        inner_subagents=inner_subagents,
    )

    return {
        "name": "summarizer",
        "description": (
            "Autonomous audited report finalizer. Runs report_writer, "
            "deterministic validators, read-only critic, and bounded repair "
            "loop before reporting pass/fail."
        ),
        "runnable": agent,
    }


__all__ = [
    "create_summarizer_agent",
    "get_summarizer_subagent",
]
