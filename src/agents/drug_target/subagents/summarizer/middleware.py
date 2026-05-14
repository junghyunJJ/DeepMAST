"""Middleware retained after the summarizer simplification (2026-05-13).

Surviving classes:

1. ``SummarizerFinalizationGuardMiddleware`` — adapted fail-closed gate.
   Captures the result of ``validate_drug_md`` and blocks
   ``generate_drug_html_report`` unless the most recent ``validate_drug_md``
   call returned ``valid=true``. This is the single mechanical protection
   that prevents the summarizer LLM from declaring ``SUMMARIZER_STATUS: PASS``
   without a real validator pass when the LLM is later instructed to render
   the HTML.

2. ``HypothesisRetryLoopMiddleware`` — out of scope for the summarizer
   simplification; used by the ``hypothesis_writer`` subagent to suppress
   identical-payload retries against the deterministic save gate.

Removed in the 2026-05-13 simplification:

- ``BuildEvidenceSummaryGuardMiddleware`` (duplicate-call protection moved to
  prompt-level guidance).
- ``RepairCycleCounterMiddleware`` (retry budget moved to prompt-level
  guidance: max 2 ``save_report_expansions`` retries).
- ``AnnotationDensityMiddleware`` (no ``save_drug_md`` tool to guard;
  ``validate_drug_md`` already covers annotation density at validation time).
- ``FrozenTemplateSpanMiddleware`` (deterministic template assembly is now
  the job of ``render_drug_md_from_expansions``; the LLM never writes
  ``drug.md`` directly).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)


def _canonical_payload_hash(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    except TypeError:
        payload = str(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        payload_hash = _canonical_payload_hash(payload)
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
        payload_hash = _canonical_payload_hash(payload)
        if payload_hash in self._rejected_payload_hashes:
            return self._blocked_response(request, payload_hash)
        result = await handler(request)
        self._record_if_rejected(payload_hash, result)
        return result


_VALIDATOR_TOOL = "validate_drug_md"
_GUARDED_FINALIZATION_TOOL = "generate_drug_html_report"


class SummarizerFinalizationGuardMiddleware(AgentMiddleware):
    """Block ``generate_drug_html_report`` until ``validate_drug_md`` passes.

    Mechanical fail-closed gate retained from the pre-simplification
    architecture and adapted to the new tool surface (2026-05-13):

    - Captures the result of every ``validate_drug_md`` call and records
      whether the most recent call returned ``valid=true``.
    - Blocks ``generate_drug_html_report`` when:
        (a) ``validate_drug_md`` has never been called in this run, OR
        (b) the most recent ``validate_drug_md`` returned ``valid=false``,
            ambiguous, or malformed output.
    - Allows the call through only after a clean ``valid=true``.

    The summarizer LLM is also instructed via the system prompt to follow the
    same contract; this middleware is the mechanical backstop.
    """

    def __init__(self) -> None:
        super().__init__()
        self._validator_called: bool = False
        self._last_valid: bool | None = None

    def _is_validator(self, request: ToolCallRequest) -> bool:
        return request.tool_call.get("name") == _VALIDATOR_TOOL

    def _is_guarded_finalization(self, request: ToolCallRequest) -> bool:
        return request.tool_call.get("name") == _GUARDED_FINALIZATION_TOOL

    def _capture_validator_result(self, result: ToolMessage | Command) -> None:
        """Read ``valid`` from the validator's JSON ToolMessage content."""
        if not isinstance(result, ToolMessage):
            return
        try:
            parsed = json.loads(str(result.content))
        except (ValueError, TypeError) as exc:
            logger.warning("validate_drug_md JSON parse failed: %s", exc)
            self._validator_called = True
            self._last_valid = False
            return
        if isinstance(parsed, dict) and "valid" in parsed:
            self._validator_called = True
            self._last_valid = bool(parsed["valid"])
        else:
            logger.warning(
                "validate_drug_md result missing 'valid' key; treating as invalid"
            )
            self._validator_called = True
            self._last_valid = False

    def _blocked(self, request: ToolCallRequest, reason: str) -> ToolMessage:
        payload = {
            "ok": False,
            "error": reason,
            "blocked_by": "SummarizerFinalizationGuard",
        }
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def _check_gate(self, request: ToolCallRequest) -> ToolMessage | None:
        if not self._is_guarded_finalization(request):
            return None
        if not self._validator_called:
            return self._blocked(
                request,
                "validate_drug_md must be called and return valid=true "
                "before generate_drug_html_report.",
            )
        if self._last_valid is not True:
            return self._blocked(
                request,
                "validate_drug_md returned valid=false; cannot finalize. "
                "Fix the offending sections via save_report_expansions and "
                "re-validate before retrying.",
            )
        return None

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        blocked = self._check_gate(request)
        if blocked is not None:
            return blocked
        result = handler(request)
        if self._is_validator(request):
            self._capture_validator_result(result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        blocked = self._check_gate(request)
        if blocked is not None:
            return blocked
        result = await handler(request)
        if self._is_validator(request):
            self._capture_validator_result(result)
        return result


__all__ = [
    "HypothesisRetryLoopMiddleware",
    "SummarizerFinalizationGuardMiddleware",
]
