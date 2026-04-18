"""Legacy literature-searcher package exports.

This package is retained for backward compatibility. It is not the
authoritative SEARCHER workflow. Use
`src.agents.deep_interpreter.subagents.prompts.SUBAGENT_PROMPTS["searcher"]`
and the matching config entry for the active SEARCHER contract.
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
