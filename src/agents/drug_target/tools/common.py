"""Common tools for Drug Target Assessment Agent.

Provides:
- think_tool: Reused from deep_interpreter (quality validation via reflection)
- validate_quality: Reused from deep_interpreter (interpretation quality scoring)
- sequential_thinking: Wraps MCP sequential-thinking server for structured planning

Note: think_tool and validate_quality use lazy imports via module __getattr__
to avoid circular import through deep_interpreter.__init__.py chain:
  deep_interpreter.__init__ → agent.py → subagents.configs
    → drug_target.integration → drug_target.agent → drug_target.subagents.configs (cycle)
"""

import asyncio
import atexit
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from langchain_core.tools import BaseTool, tool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


# =============================================================================
# Lazy re-exports (break circular import chain)
# =============================================================================

def __getattr__(name):
    """Module-level lazy imports for think_tool and validate_quality."""
    if name == "think_tool":
        import importlib
        mod = importlib.import_module("src.agents.deep_interpreter.tools.think")
        globals()["think_tool"] = mod.think_tool
        return mod.think_tool
    if name == "validate_quality":
        import importlib
        mod = importlib.import_module("src.agents.deep_interpreter.tools.quality")
        globals()["validate_quality"] = mod.validate_quality
        return mod.validate_quality
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# =============================================================================
# Sequential Thinking MCP Tool
# =============================================================================

_SEQ_THINKING_LOCK = threading.Lock()
_SEQ_THINKING_CLIENT: Optional[MultiServerMCPClient] = None
_SEQ_THINKING_TOOLS: Optional[list[BaseTool]] = None
_EXECUTOR = ThreadPoolExecutor(max_workers=2)
atexit.register(_EXECUTOR.shutdown, wait=False)


def _get_seq_thinking_config() -> dict:
    """Build MCP config for sequential-thinking server."""
    url = os.getenv("SEQ_THINKING_URL", "http://localhost:8001")
    return {
        "sequential-thinking": {
            "url": f"{url}/mcp",
            "transport": "streamable_http",
        }
    }


def _run_async(coro):
    """Run async coroutine from sync context.

    When called from an already-running event loop, delegates to a
    ThreadPoolExecutor to avoid deadlock.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        future = _EXECUTOR.submit(asyncio.run, coro)
        return future.result(timeout=120)
    else:
        return asyncio.run(coro)


def _get_seq_thinking_tools() -> list[BaseTool]:
    """Get or create cached sequential-thinking MCP tools.

    Uses a lock around the entire initialization to prevent TOCTOU race.
    Runs async client initialization via _run_async to stay sync-safe.
    """
    global _SEQ_THINKING_CLIENT, _SEQ_THINKING_TOOLS
    with _SEQ_THINKING_LOCK:
        if _SEQ_THINKING_TOOLS is not None:
            return _SEQ_THINKING_TOOLS
        config = _get_seq_thinking_config()
        client = MultiServerMCPClient(config)
        tools = _run_async(client.get_tools())
        _SEQ_THINKING_CLIENT = client
        _SEQ_THINKING_TOOLS = tools
        return tools


async def _invoke_sequential_thinking(
    thought: str,
    thought_number: int,
    total_thoughts: int,
    next_thought_needed: bool,
) -> str:
    """Invoke the sequential-thinking MCP tool."""
    tools = _get_seq_thinking_tools()

    # Find the sequentialthinking tool
    seq_tool = None
    for t in tools:
        if t.name == "sequentialthinking":
            seq_tool = t
            break

    if seq_tool is None:
        return f"[Sequential thinking unavailable] Thought {thought_number}/{total_thoughts}: {thought}"

    result = await seq_tool.ainvoke({
        "thought": thought,
        "thoughtNumber": thought_number,
        "totalThoughts": total_thoughts,
        "nextThoughtNeeded": next_thought_needed,
    })

    return str(result)


@tool
def sequential_thinking(
    thought: str,
    thought_number: int = 1,
    total_thoughts: int = 3,
    next_thought_needed: bool = True,
) -> str:
    """Structured planning and reasoning via sequential thinking.

    Use this BEFORE major operations for structured planning:
    - Break down complex tasks into steps
    - Identify strategy for database queries
    - Plan assessment approach
    - Organize document structure

    This creates a Plan step in the Plan->Execute->Reflect cycle.

    Args:
        thought: The current thought/reasoning step content
        thought_number: Current thought number (1-based)
        total_thoughts: Expected total number of thoughts
        next_thought_needed: Whether another thought step follows

    Returns:
        The processed thought result from sequential-thinking MCP
    """
    try:
        result = _run_async(_invoke_sequential_thinking(
            thought=thought,
            thought_number=thought_number,
            total_thoughts=total_thoughts,
            next_thought_needed=next_thought_needed,
        ))
        return result
    except Exception as e:
        # Graceful fallback: return the thought as-is
        logger.warning("Sequential thinking MCP failed: %s", e)
        return f"[Planning thought {thought_number}/{total_thoughts}]: {thought}"


__all__ = [
    "think_tool",
    "validate_quality",
    "sequential_thinking",
]
