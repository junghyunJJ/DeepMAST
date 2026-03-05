"""Tool-call guard middleware for write_file argument coercion.

Some models emit non-string payloads for write_file(content=...), which violates
the built-in FilesystemMiddleware schema (content: str) and raises validation errors.
This middleware normalizes write_file content to string before tool execution.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command


class WriteFileArgGuardMiddleware(AgentMiddleware):
    """Coerce write_file(content=...) arguments to string."""

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
        return handler(self._patched_request(request))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        return await handler(self._patched_request(request))

