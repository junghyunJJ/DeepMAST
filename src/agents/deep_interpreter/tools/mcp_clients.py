"""Shared MCP client management for Deep Interpreter tools.

Provides:
1. Centralized MCP server configurations (reflection-tool, biomedical-thinking, BioMCP)
2. Singleton MCP client caching to prevent resource leaks (subprocess per call)
3. Module-level ThreadPoolExecutor for sync/async bridging
4. Exact-name tool lookup to prevent unintended tool matching

Design:
- Each MCP server gets ONE cached MultiServerMCPClient + tools list
- Cache is invalidated on connection failure (auto-reconnect on next call)
- Thread-safe via module-level lock
"""

import asyncio
import atexit
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


# =============================================================================
# MCP Server Configurations
# =============================================================================

# Reflection-tool MCP server (stdio transport)
# Configure via environment variables:
# - REFLECTION_TOOL_COMMAND: Path to fastmcp executable (default: "fastmcp")
# - REFLECTION_TOOL_SERVER: Path to reflection-tool server.py (REQUIRED in CI/prod)
_REFLECTION_SERVER_CANDIDATES = [
    Path.home() / ".mcp" / "reflection_tool" / "server.py",
    Path.home() / "Dropbox" / "Metadata" / "mcp" / "reflection_tool" / "server.py",
]


def _resolve_server_path(env_var: str, candidates: list[Path]) -> str:
    """Resolve MCP server path from env var or candidate paths.

    Priority: env var > first existing candidate > first candidate (with warning).
    """
    env_val = os.getenv(env_var)
    if env_val:
        return env_val

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    # No candidate exists - use first as default but warn
    default = str(candidates[0]) if candidates else ""
    logger.warning(
        f"{env_var} not set and no server found at candidate paths. "
        f"Set {env_var} environment variable to the server.py path. "
        f"Falling back to: {default}"
    )
    return default


# Biomedical thinking MCP server (stdio transport)
# Configure via environment variables:
# - BIOMEDICAL_THINKING_COMMAND: Path to fastmcp executable (default: "fastmcp")
# - BIOMEDICAL_THINKING_SERVER: Path to biomedical-thinking server.py (REQUIRED in CI/prod)
_THINKING_SERVER_CANDIDATES = [
    Path.home() / ".mcp" / "biomedical_thinking" / "server.py",
    Path.home() / "Dropbox" / "Metadata" / "mcp" / "biomedical_thinking" / "server.py",
]

REFLECTION_TOOL_CONFIG = {
    "command": os.getenv("REFLECTION_TOOL_COMMAND", "fastmcp"),
    "args": [
        "run",
        _resolve_server_path("REFLECTION_TOOL_SERVER", _REFLECTION_SERVER_CANDIDATES),
    ],
    "transport": "stdio",
}

BIOMEDICAL_THINKING_CONFIG = {
    "command": os.getenv("BIOMEDICAL_THINKING_COMMAND", "fastmcp"),
    "args": [
        "run",
        _resolve_server_path("BIOMEDICAL_THINKING_SERVER", _THINKING_SERVER_CANDIDATES),
    ],
    "transport": "stdio",
}

# Default BioMCP server URL (HTTP/streamable_http transport)
DEFAULT_BIOMCP_URL = os.getenv("BIOMCP_URL", "http://localhost:8000/mcp")


# =============================================================================
# Module-level Singleton ThreadPoolExecutor
# =============================================================================

_EXECUTOR: ThreadPoolExecutor | None = None
_EXECUTOR_LOCK = threading.Lock()


def get_executor() -> ThreadPoolExecutor:
    """Get or create the singleton ThreadPoolExecutor for async bridging.

    Thread-safe. Used by all tools that need sync-to-async bridging.
    """
    global _EXECUTOR
    if _EXECUTOR is None:
        with _EXECUTOR_LOCK:
            if _EXECUTOR is None:
                _EXECUTOR = ThreadPoolExecutor(
                    max_workers=2, thread_name_prefix="mcp-bridge"
                )
                atexit.register(_EXECUTOR.shutdown, wait=False)
    return _EXECUTOR


# =============================================================================
# Cached MCP Client Management
# =============================================================================

# Cache: server_key -> (client, tools_list)
_CLIENT_CACHE: dict[str, tuple[MultiServerMCPClient, list[BaseTool]]] = {}
_CLIENT_LOCK = threading.Lock()
# NOTE: _CLIENT_LOCK is NEVER held across await boundaries.
# The pattern below creates the client outside the lock, then stores it
# inside the lock. Concurrent callers for the same uncached server_key may
# both create clients, but only one will be cached (the other is GC'd).


async def _get_cached_tools(
    server_key: str, server_config: dict[str, Any]
) -> list[BaseTool]:
    """Get tools from a cached MCP client, creating one if needed.

    Args:
        server_key: Unique key for the server (e.g., "reflection", "biomedical_thinking")
        server_config: MCP server configuration dict

    Returns:
        List of LangChain tool objects from the server

    Note:
        On connection failure, the cache entry is cleared so the next call
        will create a fresh client. The lock is never held across await
        boundaries to prevent event loop deadlocks in ASGI environments.
    """
    # Fast path: check cache without lock (safe dict.get)
    cached = _CLIENT_CACHE.get(server_key)
    if cached is not None:
        return cached[1]

    # Slow path: create client OUTSIDE the lock (await-safe)
    # Tool discovery is a one-time handshake; bound it so a hung MCP server
    # cannot stall every caller for the full HTTP default (~30s). Fail-closed.
    try:
        client = MultiServerMCPClient(cast(Any, {server_key: server_config}))
        tools = await asyncio.wait_for(client.get_tools(), timeout=10.0)
    except asyncio.TimeoutError:
        with _CLIENT_LOCK:
            _CLIENT_CACHE.pop(server_key, None)
        logger.warning(
            f"MCP tool discovery timed out after 10s for '{server_key}'"
        )
        raise
    except Exception:
        # Clear any partial cache entry
        with _CLIENT_LOCK:
            _CLIENT_CACHE.pop(server_key, None)
        raise

    # Store in cache WITH the lock (brief, no await)
    with _CLIENT_LOCK:
        # Double-check: another coroutine may have cached it while we awaited
        cached = _CLIENT_CACHE.get(server_key)
        if cached is not None:
            return cached[1]
        _CLIENT_CACHE[server_key] = (client, tools)
        logger.debug(
            f"MCP client cached for '{server_key}' with {len(tools)} tools"
        )

    return tools


def invalidate_client(server_key: str) -> None:
    """Invalidate a cached MCP client (e.g., after connection failure).

    Args:
        server_key: Server key to invalidate
    """
    with _CLIENT_LOCK:
        _CLIENT_CACHE.pop(server_key, None)
    logger.debug(f"MCP client cache invalidated for '{server_key}'")


def invalidate_all_clients() -> None:
    """Invalidate all cached MCP clients."""
    with _CLIENT_LOCK:
        _CLIENT_CACHE.clear()
    logger.debug("All MCP client caches invalidated")


# Register cleanup at exit
atexit.register(invalidate_all_clients)


# =============================================================================
# Tool Lookup Helpers (exact name matching)
# =============================================================================


def find_tool_by_name(tools: list[BaseTool], tool_name: str) -> BaseTool | None:
    """Find a tool by exact name match (suffix matching).

    Uses endswith() to handle MCP server name prefixes
    (e.g., "reflection__think_tool" matches "think_tool").

    Args:
        tools: List of tool objects
        tool_name: Exact tool name to find

    Returns:
        Matching tool object, or None if not found
    """
    for tool_obj in tools:
        name = getattr(tool_obj, "name", "")
        if name == tool_name or name.endswith(f"__{tool_name}"):
            return tool_obj
    return None


# =============================================================================
# High-level MCP Invocation Helpers
# =============================================================================


async def invoke_reflection_tool(reflection_text: str) -> dict:
    """Invoke the reflection-tool MCP server's think_tool.

    Uses cached client to prevent subprocess spawning on every call.

    Args:
        reflection_text: The reflection prompt to process

    Returns:
        Dictionary with success status and result
    """
    try:
        tools = await _get_cached_tools("reflection", REFLECTION_TOOL_CONFIG)
        think_tool = find_tool_by_name(tools, "think_tool")

        if think_tool is None:
            # Fallback: try partial match for backward compat
            think_tool = find_tool_by_name(tools, "think")
            if think_tool is None:
                return {
                    "success": False,
                    "error": "think_tool not found in reflection MCP server",
                    "result": None,
                }

        result = await think_tool.ainvoke({"reflection": reflection_text})

        return {
            "success": True,
            "result": str(result),
            "tool_name": think_tool.name,
        }

    except Exception as e:
        # Invalidate cache on failure so next call creates fresh client
        invalidate_client("reflection")
        return {
            "success": False,
            "error": f"Reflection-tool invocation failed: {e}",
            "result": None,
        }


async def invoke_biomedical_thinking(tool_name: str, arguments: dict) -> dict:
    """Invoke a tool on the biomedical-thinking MCP server.

    Uses cached client to prevent subprocess spawning on every call.

    Args:
        tool_name: Name of the tool to invoke
        arguments: Tool arguments dictionary

    Returns:
        Dictionary with success status and result
    """
    import json

    try:
        tools = await _get_cached_tools(
            "biomedical_thinking", BIOMEDICAL_THINKING_CONFIG
        )
        target_tool = find_tool_by_name(tools, tool_name)

        if target_tool is None:
            return {
                "success": False,
                "error": f"{tool_name} not found in biomedical-thinking MCP server",
                "result": None,
            }

        result = await target_tool.ainvoke(arguments)

        # Parse JSON string result if needed
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, ValueError):
                pass

        return {
            "success": True,
            "result": result,
            "tool_name": target_tool.name,
        }

    except Exception as e:
        invalidate_client("biomedical_thinking")
        return {
            "success": False,
            "error": f"Biomedical-thinking invocation failed: {e}",
            "result": None,
        }


async def get_biomcp_tools(
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> list[BaseTool]:
    """Get cached BioMCP tools.

    Args:
        biomcp_url: BioMCP server URL

    Returns:
        List of BioMCP tool objects
    """
    config = {"url": biomcp_url, "transport": "streamable_http"}
    return await _get_cached_tools(f"biomcp_{biomcp_url}", config)


# =============================================================================
# Sync/Async Bridge Helper
# =============================================================================


def _run_coroutine_with_timeout(coro: Any, timeout: float | None) -> Any:
    if timeout is None:
        return asyncio.run(coro)
    return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


def run_async(coro: Any, timeout: float | None = 60) -> Any:
    """Run an async coroutine from a sync context, handling event loop detection.

    Detects whether an event loop is already running and uses the appropriate
    strategy (ThreadPoolExecutor for running loop, asyncio.run for no loop).

    Args:
        coro: Async coroutine to execute
        timeout: Timeout in seconds

    Returns:
        Result of the coroutine
    """
    try:
        asyncio.get_running_loop()
        is_running = True
    except RuntimeError:
        is_running = False

    if is_running:
        future = get_executor().submit(_run_coroutine_with_timeout, coro, timeout)
        return future.result(timeout=timeout)
    else:
        return _run_coroutine_with_timeout(coro, timeout)
