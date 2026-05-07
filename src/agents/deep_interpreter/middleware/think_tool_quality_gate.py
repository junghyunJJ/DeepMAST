"""ThinkToolQualityGateMiddleware — post-handler quality gate for think_tool calls.

Enforces server-side score threshold and reflection grounding checks.
Policy references: plan §1.3 D2-D5, §1.2 R2.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)

# R2 grounding patterns: filename pattern OR numeric pattern
_FILENAME_RE = re.compile(r"[a-z0-9_]+\.json")
_NUMERIC_RE = re.compile(r"\d+(\.\d+)?")

_DEFAULT_MIN_SCORE = 0.7
_DEFAULT_MAX_RETRIES = 2


class ThinkToolQualityGateMiddleware(AgentMiddleware):
    """Post-handler quality gate for think_tool calls.

    Reads the ToolMessage content returned by the handler and applies:
    - D2: score gate — parsed_score < min_score → retry
    - D3: retry cap — _retry_count >= max_retries → blocked
    - D4: None-score — parsed_score is None → strict fail (retry)
    - D5: clamp — LLM-supplied score_threshold in request args is ignored
    - R2: grounding — reflection must contain filename or numeric pattern
    """

    def __init__(
        self,
        min_score: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        super().__init__()
        self._min_score: float = (
            min_score
            if min_score is not None
            else float(os.environ.get("THINK_TOOL_MIN_SCORE", str(_DEFAULT_MIN_SCORE)))
        )
        self._max_retries: int = (
            max_retries
            if max_retries is not None
            else int(os.environ.get("THINK_TOOL_MAX_RETRIES", str(_DEFAULT_MAX_RETRIES)))
        )
        self._retry_count: int = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_think_tool(request: ToolCallRequest) -> bool:
        return request.tool_call.get("name") == "think_tool"

    def _has_grounding(self, reflection: object) -> bool:
        if not isinstance(reflection, str):
            return False
        return bool(_FILENAME_RE.search(reflection) or _NUMERIC_RE.search(reflection))

    def _build_retry_message(self, tool_call_id: str, reason: str) -> ToolMessage:
        self._retry_count += 1
        payload = {"retry": True, "reason": reason, "attempt": self._retry_count}
        return ToolMessage(content=json.dumps(payload), tool_call_id=tool_call_id)

    def _build_blocked_message(self, tool_call_id: str, reason: str) -> ToolMessage:
        payload = {"blocked": True, "reason": reason, "attempts": self._retry_count}
        return ToolMessage(content=json.dumps(payload), tool_call_id=tool_call_id)

    def _evaluate(
        self, request: ToolCallRequest, result: ToolMessage
    ) -> ToolMessage:
        """Apply quality gates; return retry/blocked/pass-through ToolMessage."""
        tool_call_id: str = request.tool_call.get("id", "")

        # Parse handler content
        try:
            data: dict = json.loads(result.content)
        except (json.JSONDecodeError, TypeError):
            data = {}

        parsed_score = data.get("parsed_score")  # may be float or None
        reflection_text = data.get("result", "")

        # D3 check before adding another retry: if already exhausted → blocked
        if self._retry_count >= self._max_retries:
            return self._build_blocked_message(
                tool_call_id,
                f"Max retries ({self._max_retries}) exhausted for think_tool quality gate.",
            )

        # D4: None score → strict fail
        if parsed_score is None:
            return self._build_retry_message(
                tool_call_id,
                "think_tool returned no parseable score (parsed_score=None); retry required.",
            )

        # D2: score gate (D5: ignore LLM score_threshold — use server-side only)
        if parsed_score < self._min_score:
            return self._build_retry_message(
                tool_call_id,
                f"Score {parsed_score:.3f} is below threshold {self._min_score:.3f}.",
            )

        # R2: grounding check
        if not self._has_grounding(reflection_text):
            return self._build_retry_message(
                tool_call_id,
                "Reflection lacks grounding evidence (no filename pattern or numeric value).",
            )

        # All checks passed — reset counter and pass through
        self._retry_count = 0
        return result

    # ------------------------------------------------------------------
    # AgentMiddleware interface
    # ------------------------------------------------------------------

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if not self._is_think_tool(request):
            return handler(request)
        result = handler(request)
        if not isinstance(result, ToolMessage):
            return result
        return self._evaluate(request, result)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if not self._is_think_tool(request):
            return await handler(request)
        result = await handler(request)
        if not isinstance(result, ToolMessage):
            return result
        return self._evaluate(request, result)
