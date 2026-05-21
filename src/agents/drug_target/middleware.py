"""Middleware for the drug_target agent package.

Retained from the 2026-05-13 summarizer simplification.
``HypothesisRetryLoopMiddleware`` is out of scope for the
summarizer→finalize_report migration (used by hypothesis_writer to suppress
identical-payload retries against the deterministic save gate).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.drug_target.tools.report_expansion_schema import canonical_json_hash


class HypothesisRetryLoopMiddleware(AgentMiddleware):
    """Block unchanged retries after a deterministic hypothesis-save rejection.

    Used by the ``hypothesis_writer`` subagent. Out of scope for the
    2026-05-13 summarizer simplification.
    """

    def __init__(self) -> None:
        super().__init__()
        self._rejected_payload_hashes: set[str] = set()

    def _payload_for_request(self, request: ToolCallRequest) -> Any | None:
        tool_name = request.tool_call.get("name")
        args = request.tool_call.get("args") or {}
        if not isinstance(args, dict):
            return None
        if tool_name == "save_hypothesis_report":
            return args.get("report")
        if tool_name == "save_evidence" and args.get("filename") == "hypothesis_report.json":
            return args.get("data")
        return None

    def _blocked_response(self, request: ToolCallRequest, payload_hash: str) -> ToolMessage:
        payload = {
            "saved": False,
            "error": (
                "Identical hypothesis_report payload was already rejected by a "
                "deterministic save gate. Mutate the payload according to the "
                "previous errors before retrying."
            ),
            "payload_hash": payload_hash,
        }
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def _record_if_rejected(self, payload_hash: str, result: ToolMessage | Command) -> None:
        if not isinstance(result, ToolMessage):
            return
        try:
            parsed = json.loads(str(result.content))
        except Exception:
            return
        if isinstance(parsed, dict) and parsed.get("saved") is False:
            self._rejected_payload_hashes.add(payload_hash)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        payload = self._payload_for_request(request)
        if payload is None:
            return handler(request)
        payload_hash = canonical_json_hash(payload)
        if payload_hash in self._rejected_payload_hashes:
            return self._blocked_response(request, payload_hash)
        result = handler(request)
        self._record_if_rejected(payload_hash, result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        payload = self._payload_for_request(request)
        if payload is None:
            return await handler(request)
        payload_hash = canonical_json_hash(payload)
        if payload_hash in self._rejected_payload_hashes:
            return self._blocked_response(request, payload_hash)
        result = await handler(request)
        self._record_if_rejected(payload_hash, result)
        return result
