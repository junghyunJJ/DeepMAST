"""Summarizer-specific AgentMiddleware implementations.

Middlewares:
1. BuildEvidenceSummaryGuardMiddleware: Allow build_evidence_summary exactly
   once per agent run; block subsequent calls with a structured error.
2. RepairCycleCounterMiddleware: Block the third task(subagent_type="report_writer")
   after 2 non-converging critic cycles.
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

_BUILD_EVIDENCE_TOOL = "build_evidence_summary"


class BuildEvidenceSummaryGuardMiddleware(AgentMiddleware):
    """Allow build_evidence_summary exactly once per agent run.

    On the second invocation within the same middleware instance, returns a
    blocked ToolMessage directing the agent to follow REPAIR MODE without
    rebuilding the evidence summary skeleton.
    """

    def __init__(self) -> None:
        super().__init__()
        self._call_count: int = 0

    def _is_build_evidence(self, request: ToolCallRequest) -> bool:
        return request.tool_call.get("name") == _BUILD_EVIDENCE_TOOL

    def _blocked_response(self, request: ToolCallRequest) -> ToolMessage:
        payload = {
            "already_invoked": True,
            "error": (
                "build_evidence_summary has already been called once in this agent run. "
                "The drug.md skeleton already exists on disk. "
                "STOP — do NOT call build_evidence_summary again. "
                "Follow REPAIR MODE: load_evidence_files('drug.md') then patch in-place."
            ),
        }
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if self._is_build_evidence(request):
            if self._call_count >= 1:
                logger.warning(
                    "BuildEvidenceSummaryGuardMiddleware: blocking duplicate "
                    "build_evidence_summary call (count=%d)",
                    self._call_count,
                )
                return self._blocked_response(request)
            self._call_count += 1
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if self._is_build_evidence(request):
            if self._call_count >= 1:
                logger.warning(
                    "BuildEvidenceSummaryGuardMiddleware: blocking duplicate "
                    "build_evidence_summary call (count=%d)",
                    self._call_count,
                )
                return self._blocked_response(request)
            self._call_count += 1
        return await handler(request)


_REPORT_WRITER_SUBAGENT = "report_writer"
_MAX_REPAIR_CYCLES_DEFAULT = 2


class RepairCycleCounterMiddleware(AgentMiddleware):
    """Block the third task(subagent_type="report_writer") after max_cycles.

    Inner subagents (critic, report_writer) are dispatched via the deepagents
    built-in `task` tool. This middleware tracks how many times the
    report_writer subagent has been invoked and blocks the (max_cycles+1)th
    call, returning a BLOCKED ToolMessage with the last known critic findings.
    """

    def __init__(self, *, max_cycles: int = _MAX_REPAIR_CYCLES_DEFAULT) -> None:
        super().__init__()
        self._max_cycles = max_cycles
        self._report_writer_count: int = 0
        self._last_critic_findings: str = ""

    def _subagent_type(self, request: ToolCallRequest) -> str | None:
        if request.tool_call.get("name") != "task":
            return None
        args = request.tool_call.get("args") or {}
        if isinstance(args, dict):
            return args.get("subagent_type")
        return None

    def _blocked_response(self, request: ToolCallRequest) -> ToolMessage:
        payload = {
            "status": "BLOCKED",
            "reason": (
                f"report_writer has been invoked {self._report_writer_count} time(s). "
                f"Max repair cycles ({self._max_cycles}) reached. "
                "The report has not converged after the allowed repair attempts. "
                "Terminate this run and surface the critic findings below."
            ),
            "critic_findings": self._last_critic_findings or "No findings recorded.",
        }
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def _handle_critic_result(self, result: ToolMessage | Command) -> None:
        """Extract critic findings from tool result for use in BLOCKED message."""
        if isinstance(result, ToolMessage):
            self._last_critic_findings = str(result.content)
        elif isinstance(result, Command):
            # Command may wrap a ToolMessage in its update
            update = getattr(result, "update", None)
            if isinstance(update, dict):
                msgs = update.get("messages", [])
                if msgs:
                    last = msgs[-1]
                    if isinstance(last, ToolMessage):
                        self._last_critic_findings = str(last.content)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        subagent = self._subagent_type(request)
        if subagent == _REPORT_WRITER_SUBAGENT:
            if self._report_writer_count >= self._max_cycles:
                logger.warning(
                    "RepairCycleCounterMiddleware: blocking report_writer "
                    "(count=%d, max=%d)",
                    self._report_writer_count,
                    self._max_cycles,
                )
                return self._blocked_response(request)
            self._report_writer_count += 1
            result = handler(request)
            return result
        result = handler(request)
        if subagent == "critic":
            self._handle_critic_result(result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        subagent = self._subagent_type(request)
        if subagent == _REPORT_WRITER_SUBAGENT:
            if self._report_writer_count >= self._max_cycles:
                logger.warning(
                    "RepairCycleCounterMiddleware: blocking report_writer "
                    "(count=%d, max=%d)",
                    self._report_writer_count,
                    self._max_cycles,
                )
                return self._blocked_response(request)
            self._report_writer_count += 1
            result = await handler(request)
            return result
        result = await handler(request)
        if subagent == "critic":
            self._handle_critic_result(result)
        return result


__all__ = [
    "BuildEvidenceSummaryGuardMiddleware",
    "RepairCycleCounterMiddleware",
]
