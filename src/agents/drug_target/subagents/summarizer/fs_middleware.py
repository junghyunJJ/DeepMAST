"""LoggingFilesystemMiddleware: subclass of deepagents.FilesystemMiddleware
that captures the raw LLM-supplied args for ``ls`` and ``glob`` calls via
``wrap_tool_call`` / ``awrap_tool_call`` BEFORE backend invocation.

Goal: pressure-test plan hypothesis (b) "LLM path mistake" by detecting
``raw_input != validated_input AND validated_input resolves to populated
dir on disk``.

Mechanism (b) chosen over mechanism (a):
    deepagents 0.5.3 ``_create_ls_tool`` and ``_create_glob_tool`` each return
    a single ``BaseTool`` instance (not a (sync, async) tuple as the original
    plan spec assumed). Overriding those methods to return a different shape
    would break the parent ``__init__`` wiring. Instead, we intercept at the
    ``wrap_tool_call`` layer which receives the complete ``ToolCallRequest``
    with the raw ``tool_call.args`` dict before any path validation.

Empirically verified on deepagents 0.5.3: subclassing FilesystemMiddleware
and passing it via ``create_deep_agent(middleware=[...])`` does NOT raise
``AssertionError: Please remove duplicate middleware instances``.

Logger name: ``drug_target.fs_middleware``
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from deepagents.middleware.filesystem import FilesystemMiddleware

logger = logging.getLogger("drug_target.fs_middleware")

_LOG_TRUNC = 500
_LOGGED_TOOLS = frozenset({"ls", "glob"})


def _sanitize_for_log(value: object) -> str:
    """Strip newlines/CR/null bytes; truncate to _LOG_TRUNC chars (CP-P1-003)."""
    if value is None:
        return ""
    s = str(value).replace("\n", "\\n").replace("\r", "\\r").replace("\x00", "\\x00")
    if len(s) > _LOG_TRUNC:
        s = s[:_LOG_TRUNC] + "...[TRUNCATED]"
    return s


class LoggingFilesystemMiddleware(FilesystemMiddleware):
    """Intercepts ``ls``/``glob`` tool calls to log raw args before execution.

    Overrides ``wrap_tool_call`` and ``awrap_tool_call`` from the parent to
    emit a single DEBUG-level structured JSON record per intercepted call.
    All other tool calls and all other middleware behavior are passed through
    to the parent unchanged.

    The raw ``tool_call.args`` dict is sanitized (CP-P1-003) before logging so
    that LLM-generated path strings containing newlines, null bytes, or
    excessively long values cannot inject fake log lines.
    """

    def wrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        """Log raw args for ls/glob calls, then delegate to parent handler."""
        tool_name = request.tool_call.get("name", "") if hasattr(request.tool_call, "get") else ""
        if tool_name in _LOGGED_TOOLS:
            raw_args = request.tool_call.get("args", {}) or {}
            logger.debug(
                json.dumps(
                    {
                        "layer": "middleware",
                        "tool": tool_name,
                        "raw_args": {
                            k: _sanitize_for_log(v) for k, v in raw_args.items()
                        },
                        "timestamp": time.time(),
                    }
                )
            )
        return super().wrap_tool_call(request, handler)

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        """Async variant: log raw args for ls/glob calls, then delegate."""
        tool_name = request.tool_call.get("name", "") if hasattr(request.tool_call, "get") else ""
        if tool_name in _LOGGED_TOOLS:
            raw_args = request.tool_call.get("args", {}) or {}
            logger.debug(
                json.dumps(
                    {
                        "layer": "middleware",
                        "tool": tool_name,
                        "raw_args": {
                            k: _sanitize_for_log(v) for k, v in raw_args.items()
                        },
                        "timestamp": time.time(),
                    }
                )
            )
        return await super().awrap_tool_call(request, handler)
