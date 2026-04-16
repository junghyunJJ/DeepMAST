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
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from langchain_core.runnables import RunnableConfig
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


def _shutdown_seq_thinking() -> None:
    """P2-4: graceful shutdown — close MCP client first, then drain executor.

    Pre-fix: ThreadPoolExecutor.shutdown(wait=False) truncated in-flight
    asyncio.run(coro) calls and never explicitly closed _SEQ_THINKING_CLIENT.
    Post-fix: close client (if connected), then drain executor with bounded wait.
    """
    global _SEQ_THINKING_CLIENT
    try:
        client = _SEQ_THINKING_CLIENT
        if client is not None:
            close = getattr(client, "aclose", None) or getattr(client, "close", None)
            if callable(close):
                try:
                    if asyncio.iscoroutinefunction(close):
                        asyncio.run(close())
                    else:
                        close()
                except Exception:
                    pass
            _SEQ_THINKING_CLIENT = None
    except Exception:
        pass
    try:
        # wait=True so threads finish active work; cancel_futures drops queued ones.
        # Bounded by Python interpreter exit; no separate timeout knob exists on
        # ThreadPoolExecutor.shutdown — at-exit context naturally bounds wait.
        _EXECUTOR.shutdown(wait=True, cancel_futures=True)
    except Exception:
        pass


atexit.register(_shutdown_seq_thinking)


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

    P3-2: timeout is configurable via env var SEQ_THINKING_TIMEOUT (default 120s).
    On timeout, future.cancel() is called to release executor capacity (best-effort
    — already-running tasks cannot be cancelled but queued ones can).
    """
    import concurrent.futures as _cf

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        try:
            timeout = float(os.getenv("SEQ_THINKING_TIMEOUT", "120"))
        except (TypeError, ValueError):
            timeout = 120.0
        future = _EXECUTOR.submit(asyncio.run, coro)
        try:
            return future.result(timeout=timeout)
        except _cf.TimeoutError:
            future.cancel()
            raise
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


# =============================================================================
# Per-session state for degenerate-loop detection
# =============================================================================
# The underlying MCP sequential-thinking tool does not enforce monotonicity.
# OSS models like qwen3.5 can fall into a degenerate self-reinforcing loop
# where the same thoughtNumber is resubmitted dozens of times, exhausting the
# recursion budget without making progress (observed: ~456s / 22 repeats on
# qwen1 before hypothesis_writer timed out with an empty result).
#
# We track (thread_id -> {last_n, repeats, history_len}) to:
#   1. Reject non-monotonic thought_number values
#   2. Detect 3+ consecutive calls at the same thought_number and force an
#      explicit escape message that instructs the model to call save_evidence
#   3. Cap total thought history at 30 to prevent unbounded drift
#
# State is process-local; LangGraph runs one subagent per thread at a time.

_THINKING_STATE: dict[str, dict[str, int]] = {}
_THINKING_STATE_LOCK = threading.Lock()
_THINKING_HISTORY_CAP = 30
_THINKING_REPEAT_LIMIT = 3


def _thinking_session_key(config: Optional[RunnableConfig]) -> str:
    """Derive a stable per-subagent-turn key from RunnableConfig.

    Each LangGraph subagent (evidence_assessor, deep_diver, hypothesis_writer,
    report_writer) runs sequentially under the same parent thread_id. If the
    counter is scoped only by thread_id, a fresh subagent's legitimate
    thoughtNumber=1 gets falsely rejected because the previous subagent left
    last_n=8 in state.

    We therefore include the current graph node / subagent namespace so each
    subagent turn starts with a clean counter. ``langgraph_node`` is set by
    LangGraph while a node is executing; ``checkpoint_ns`` is namespaced by
    deep-agent subagent path. When neither is present (e.g., tests invoking
    the tool directly) we fall back to a process-local "default" key.
    """
    if not config:
        return "default"
    configurable = config.get("configurable", {}) or {}
    metadata = config.get("metadata", {}) or {}
    thread_id = configurable.get("thread_id", "default")
    # Prefer the per-node identifier so each subagent turn has its own counter.
    # LangGraph exposes this via metadata.langgraph_node during execution;
    # deep-agents also surfaces a nested checkpoint_ns per subagent.
    node = (
        metadata.get("langgraph_node")
        or configurable.get("langgraph_node")
        or configurable.get("checkpoint_ns", "")
    )
    return f"{thread_id}::{node}"


def _reset_thinking_state(session_key: str) -> None:
    """Reset state for a session key (exposed for tests)."""
    with _THINKING_STATE_LOCK:
        _THINKING_STATE.pop(session_key, None)


def _check_thinking_monotonicity(
    session_key: str,
    thought_number: int,
) -> Optional[str]:
    """Return a guard message JSON string if the call must be blocked.

    Returns None if the call is allowed to proceed to the MCP tool.

    Self-heals on ``thought_number == 1``: if a caller submits 1 it is
    always treated as the start of a fresh thinking sequence, even if
    the session key matches a previous subagent's counter. This is a
    second line of defense against overly-coarse session keys that
    might otherwise false-block a fresh subagent turn.
    """
    with _THINKING_STATE_LOCK:
        # Self-heal: thought_number=1 means "new sequence", always reset.
        if thought_number <= 1:
            _THINKING_STATE[session_key] = {
                "last_n": thought_number,
                "repeats": 0,
                "history_len": 1,
            }
            return None

        state = _THINKING_STATE.setdefault(
            session_key,
            {"last_n": 0, "repeats": 0, "history_len": 0},
        )

        # Reject non-monotonic regressions (e.g., thoughtNumber=3 after last=5)
        if thought_number < state["last_n"]:
            return json.dumps({
                "error": "non_monotonic_thought_number",
                "last_thought_number": state["last_n"],
                "submitted": thought_number,
                "instruction": (
                    f"thoughtNumber must be >= {state['last_n']}. "
                    "If you are done thinking, set nextThoughtNeeded=false and "
                    "proceed to the next action (for hypothesis_writer: "
                    "save_evidence(data_dir, 'hypothesis_report.json', ...))."
                ),
            })

        # Detect stuck-in-loop (same thoughtNumber, multiple consecutive calls)
        if thought_number == state["last_n"] and thought_number > 0:
            state["repeats"] += 1
            if state["repeats"] >= _THINKING_REPEAT_LIMIT:
                state["repeats"] = 0  # reset so next distinct call proceeds
                return json.dumps({
                    "error": "degenerate_loop_detected",
                    "thought_number": thought_number,
                    "repeats": _THINKING_REPEAT_LIMIT,
                    "instruction": (
                        f"Detected {_THINKING_REPEAT_LIMIT} consecutive "
                        "sequential_thinking calls at thoughtNumber="
                        f"{thought_number}. You are stuck. STOP calling "
                        "sequential_thinking. Emit your best-effort output "
                        "now: for hypothesis_writer call "
                        "save_evidence(data_dir, 'hypothesis_report.json', "
                        "<your best draft>) IMMEDIATELY. For report_writer "
                        "call save_drug_md with the current draft. For "
                        "evidence_assessor/deep_diver proceed to the next "
                        "tool in the workflow."
                    ),
                })
        else:
            state["repeats"] = 0
            state["last_n"] = thought_number

        state["history_len"] += 1
        if state["history_len"] > _THINKING_HISTORY_CAP:
            return json.dumps({
                "error": "thought_history_exceeded",
                "history_len": state["history_len"],
                "cap": _THINKING_HISTORY_CAP,
                "instruction": (
                    f"thoughtHistoryLength exceeded {_THINKING_HISTORY_CAP}. "
                    "You must conclude analysis and emit your final output "
                    "now (save_evidence for hypothesis_writer, save_drug_md "
                    "for report_writer, or the appropriate stage tool)."
                ),
            })

    return None


@tool
def sequential_thinking(
    thought: str,
    thought_number: int = 1,
    total_thoughts: int = 3,
    next_thought_needed: bool = True,
    config: Optional[RunnableConfig] = None,
) -> str:
    """Structured planning and reasoning via sequential thinking.

    Use this BEFORE major operations for structured planning:
    - Break down complex tasks into steps
    - Identify strategy for database queries
    - Plan assessment approach
    - Organize document structure

    This creates a Plan step in the Plan->Execute->Reflect cycle.

    Guardrails (enforced server-side to prevent degenerate loops):
    - thought_number must be monotonically non-decreasing
    - 3 consecutive calls at the same thought_number triggers an explicit
      escape instruction to proceed with save_evidence / save_drug_md
    - thoughtHistoryLength is capped at 30 per session

    Args:
        thought: The current thought/reasoning step content
        thought_number: Current thought number (1-based, monotonic)
        total_thoughts: Expected total number of thoughts
        next_thought_needed: Whether another thought step follows
        config: Injected by LangChain tool framework — used to derive
            a per-subagent-session state key for loop detection.

    Returns:
        The processed thought result from sequential-thinking MCP, or
        an error+instruction JSON when a guard is triggered.
    """
    session_key = _thinking_session_key(config)
    guard = _check_thinking_monotonicity(session_key, thought_number)
    if guard is not None:
        logger.warning(
            "sequential_thinking guard triggered (session=%s, n=%d): %s",
            session_key, thought_number, guard,
        )
        return guard

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
