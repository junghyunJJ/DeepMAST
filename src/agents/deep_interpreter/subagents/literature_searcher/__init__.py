"""Literature Searcher SubAgent - CompiledSubAgent with BioMCP workflow.

This subagent performs proactive literature search using the BioMCP workflow:
think → article_searcher → quality validation loop

It is designed to be called BEFORE interpretation to provide a reference
foundation for literature-grounded interpretations.
"""

from src.agents.deep_interpreter.subagents.literature_searcher.agent import (
    create_literature_searcher_agent,
    get_literature_searcher_config,
    LITERATURE_SEARCHER_SYSTEM_PROMPT,
)

__all__ = [
    "create_literature_searcher_agent",
    "get_literature_searcher_config",
    "LITERATURE_SEARCHER_SYSTEM_PROMPT",
]
