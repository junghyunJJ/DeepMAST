"""Tool-call guard middlewares for the Drug Target agent pipeline.

Middlewares:
1. WriteFileArgGuardMiddleware: Coerces write_file(content=...) to string and
   blocks write_file calls targeting output artifacts.
2. ReadFileBlockMiddleware: Blocks read_file calls at the orchestrator level so
   the LLM cannot bypass subagent delegation by reading evidence files directly.
3. SubagentErrorGuardMiddleware: Catches GraphRecursionError from subagent task
   calls so the orchestrator can continue to the next subagent instead of crashing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)


# Output artifacts that MUST NOT be written via write_file.
_BLOCKED_ARTIFACT_NAMES = ("target_assessment.json", "drug.md", "hypothesis_report.json")

_BLOCKED_ARTIFACT_ERROR = (
    "ERROR: Do not use write_file for output artifacts. "
    "Use save_target_assessment for target_assessment.json, "
    "save_drug_md for drug.md, and "
    "save_evidence(data_dir, 'hypothesis_report.json', data) for hypothesis_report.json."
)


class ReadOnlyToolGuardMiddleware(AgentMiddleware):
    """Block write-capable tools for read-only reviewer subagents."""

    def __init__(
        self,
        *,
        blocked_tool_names: tuple[str, ...] = (),
        block_write_file: bool = True,
    ) -> None:
        super().__init__()
        self.blocked_tool_names = set(blocked_tool_names)
        self.block_write_file = block_write_file

    def _is_blocked(self, request: ToolCallRequest) -> bool:
        tool_name = request.tool_call.get("name")
        if self.block_write_file and tool_name == "write_file":
            return True
        return tool_name in self.blocked_tool_names

    @staticmethod
    def _blocked_response(request: ToolCallRequest) -> ToolMessage:
        tool_name = request.tool_call.get("name", "unknown")
        return ToolMessage(
            content=(
                f"ERROR: `{tool_name}` is not available in this read-only "
                "review context. Return audit findings instead of modifying files."
            ),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if self._is_blocked(request):
            return self._blocked_response(request)
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if self._is_blocked(request):
            return self._blocked_response(request)
        return await handler(request)


class WriteFileArgGuardMiddleware(AgentMiddleware):
    """Coerce write_file(content=...) arguments to string and block output artifacts."""

    @staticmethod
    def _coerce_content(value: Any) -> str:
        if isinstance(value, str):
            return value
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, indent=2, ensure_ascii=False, default=str)
        return str(value)

    @classmethod
    def _is_blocked_artifact(cls, request: ToolCallRequest) -> bool:
        """Return True if write_file targets a protected output artifact."""
        tool_call = request.tool_call
        if tool_call.get("name") != "write_file":
            return False
        args = tool_call.get("args")
        if not isinstance(args, dict):
            return False
        path = str(args.get("path", "") or args.get("file_path", ""))
        return any(name in path for name in _BLOCKED_ARTIFACT_NAMES)

    @classmethod
    def _blocked_response(cls, request: ToolCallRequest) -> ToolMessage:
        """Return an error ToolMessage for blocked artifact writes."""
        return ToolMessage(
            content=_BLOCKED_ARTIFACT_ERROR,
            tool_call_id=request.tool_call.get("id", ""),
        )

    @classmethod
    def _patched_request(cls, request: ToolCallRequest) -> ToolCallRequest:
        tool_call = request.tool_call
        if tool_call.get("name") != "write_file":
            return request

        args = tool_call.get("args")
        if not isinstance(args, dict):
            return request
        if "content" not in args:
            return request

        content = args["content"]
        if isinstance(content, str):
            return request

        patched_args = {**args, "content": cls._coerce_content(content)}
        patched_call = {**tool_call, "args": patched_args}
        return request.override(tool_call=patched_call)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if self._is_blocked_artifact(request):
            return self._blocked_response(request)
        return handler(self._patched_request(request))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if self._is_blocked_artifact(request):
            return self._blocked_response(request)
        return await handler(self._patched_request(request))


# ---------------------------------------------------------------------------
# Fix 2: Block read_file at orchestrator level
# ---------------------------------------------------------------------------

_READ_FILE_BLOCKED_MSG = (
    "ERROR: read_file is not available at the orchestrator level. "
    "Do NOT read evidence files yourself. Instead, use the `task` tool to delegate "
    "to the next subagent in sequence: evidence_assessor → hypothesis_writer → "
    "summarizer. Each subagent handles its own file I/O."
)


class ReadFileBlockMiddleware(AgentMiddleware):
    """Block read_file calls at the orchestrator level.

    The orchestrator LLM should only use load_lr_candidates (once) and
    the task tool (4 times). read_file bypasses the subagent delegation
    pattern and wastes orchestrator steps.
    """

    @staticmethod
    def _is_read_file(request: ToolCallRequest) -> bool:
        return request.tool_call.get("name") == "read_file"

    @classmethod
    def _blocked_response(cls, request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=_READ_FILE_BLOCKED_MSG,
            tool_call_id=request.tool_call.get("id", ""),
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if self._is_read_file(request):
            return self._blocked_response(request)
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if self._is_read_file(request):
            return self._blocked_response(request)
        return await handler(request)


# ---------------------------------------------------------------------------
# Fix 4: Catch GraphRecursionError from subagent task calls
# ---------------------------------------------------------------------------

class SubagentErrorGuardMiddleware(AgentMiddleware):
    """Catch GraphRecursionError from subagent task calls.

    When a subagent hits its recursion limit, this middleware catches the
    error and returns a graceful ToolMessage so the orchestrator can
    continue to the next subagent instead of crashing entirely.
    """

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        try:
            return handler(request)
        except Exception as exc:
            if "GraphRecursionError" in type(exc).__name__:
                logger.warning(
                    "Subagent hit recursion limit (tool=%s): %s",
                    request.tool_call.get("name", "unknown"),
                    exc,
                )
                tool_args = request.tool_call.get("args", {})
                subagent_type = ""
                if isinstance(tool_args, dict):
                    subagent_type = tool_args.get("subagent_type", "unknown")
                return ToolMessage(
                    content=(
                        f"CRITICAL: Subagent '{subagent_type}' hit recursion limit "
                        f"and could NOT complete all tasks. "
                        f"Error: {type(exc).__name__}. "
                        f"BEFORE proceeding, call check_stage1_completion(data_dir) "
                        f"to verify pipeline integrity."
                    ),
                    tool_call_id=request.tool_call.get("id", ""),
                )
            raise

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        try:
            return await handler(request)
        except Exception as exc:
            if "GraphRecursionError" in type(exc).__name__:
                logger.warning(
                    "Subagent hit recursion limit (tool=%s): %s",
                    request.tool_call.get("name", "unknown"),
                    exc,
                )
                tool_args = request.tool_call.get("args", {})
                subagent_type = ""
                if isinstance(tool_args, dict):
                    subagent_type = tool_args.get("subagent_type", "unknown")
                return ToolMessage(
                    content=(
                        f"CRITICAL: Subagent '{subagent_type}' hit recursion limit "
                        f"and could NOT complete all tasks. "
                        f"Error: {type(exc).__name__}. "
                        f"BEFORE proceeding, call check_stage1_completion(data_dir) "
                        f"to verify pipeline integrity."
                    ),
                    tool_call_id=request.tool_call.get("id", ""),
                )
            raise
