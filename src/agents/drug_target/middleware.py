"""Middleware for the drug_target agent package.

Retained from the 2026-05-13 summarizer simplification.
``HypothesisRetryLoopMiddleware`` is out of scope for the
summarizer→finalize_report migration (used by hypothesis_writer to suppress
identical-payload retries against the deterministic save gate).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import hook_config
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.drug_target.tools.report_expansion_schema import canonical_json_hash


class HypothesisRetryLoopMiddleware(AgentMiddleware):
    """Block unchanged retries after a deterministic hypothesis-save rejection.

    Used by the ``hypothesis_writer`` subagent. Out of scope for the
    2026-05-13 summarizer simplification.
    """

    def __init__(
        self,
        *,
        stop_after_first_save: bool = False,
        max_hypothesis_save_attempts: int | None = None,
        single_read_skill_paths: Sequence[str] = (),
    ) -> None:
        super().__init__()
        self._stop_after_first_save = stop_after_first_save
        self._max_hypothesis_save_attempts = max_hypothesis_save_attempts
        self._single_read_skill_paths = tuple(single_read_skill_paths)
        self._seen_single_read_skill_paths: set[str] = set()
        self._rejected_payload_hashes: set[str] = set()
        self._hypothesis_save_seen = False
        self._hypothesis_save_attempts = 0
        self._hypothesis_stop_requested = False

    def _skill_read_path(self, request: ToolCallRequest) -> str | None:
        if request.tool_call.get("name") != "read_skill_file":
            return None
        args = request.tool_call.get("args") or {}
        if not isinstance(args, dict):
            return None
        skill_path = args.get("skill_path")
        return skill_path if isinstance(skill_path, str) else None

    def _blocked_duplicate_skill_read_response(
        self,
        request: ToolCallRequest,
        skill_path: str,
    ) -> ToolMessage:
        return ToolMessage(
            content=(
                "Skill guide already loaded earlier in this hypothesis_writer run: "
                f"{skill_path}. Reuse the already-read guidance; do not call "
                "read_skill_file again for this skill."
            ),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def _should_single_read_skill_path(self, skill_path: str) -> bool:
        return skill_path in self._single_read_skill_paths

    def _is_hypothesis_report_save_request(self, request: ToolCallRequest) -> bool:
        tool_name = request.tool_call.get("name")
        if tool_name == "save_hypothesis_report":
            return True
        args = request.tool_call.get("args") or {}
        return (
            tool_name == "save_evidence"
            and isinstance(args, dict)
            and args.get("filename") == "hypothesis_report.json"
        )

    def _record_hypothesis_save_result(self, request: ToolCallRequest) -> None:
        if not self._stop_after_first_save:
            return
        if not self._is_hypothesis_report_save_request(request):
            return
        self._hypothesis_save_seen = True
        self._hypothesis_stop_requested = True

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

    def _blocked_after_save_response(self, request: ToolCallRequest) -> ToolMessage:
        payload = {
            "saved": False,
            "error": (
                "hypothesis_report save already completed in this subagent turn. "
                "Stop now so the graph-native hypothesis quality retry can apply "
                "the bounded retry policy."
            ),
        }
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def _blocked_after_attempt_limit_response(
        self, request: ToolCallRequest
    ) -> ToolMessage:
        payload = {
            "saved": False,
            "error": (
                "hypothesis_report save attempt limit reached in this subagent "
                "turn. Stop now so the graph-native hypothesis quality retry "
                "can apply the bounded retry policy."
            ),
            "attempts": self._hypothesis_save_attempts,
            "max_attempts": self._max_hypothesis_save_attempts,
        }
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=request.tool_call.get("id", ""),
        )

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

    def _save_attempt_limit_reached(self) -> bool:
        return (
            self._max_hypothesis_save_attempts is not None
            and self._hypothesis_save_attempts >= self._max_hypothesis_save_attempts
        )

    def _record_save_attempt(self, request: ToolCallRequest) -> None:
        if self._is_hypothesis_report_save_request(request):
            self._hypothesis_save_attempts += 1

    def _result_saved_false(self, result: ToolMessage | Command) -> bool:
        if not isinstance(result, ToolMessage):
            return False
        try:
            parsed = json.loads(str(result.content))
        except Exception:
            return False
        return isinstance(parsed, dict) and parsed.get("saved") is False

    def _record_if_rejected(self, payload_hash: str, result: ToolMessage | Command) -> None:
        if not isinstance(result, ToolMessage):
            return
        try:
            parsed = json.loads(str(result.content))
        except Exception:
            return
        if isinstance(parsed, dict) and parsed.get("saved") is False:
            self._rejected_payload_hashes.add(payload_hash)

    def _jump_to_end_if_requested(self) -> dict[str, str] | None:
        if self._hypothesis_stop_requested:
            self._hypothesis_stop_requested = False
            return {"jump_to": "end"}
        return None

    @hook_config(can_jump_to=["end"])
    def after_model(self, state: Any, runtime: Any) -> dict[str, str] | None:
        return self._jump_to_end_if_requested()

    @hook_config(can_jump_to=["end"])
    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, str] | None:
        return self._jump_to_end_if_requested()

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        skill_path = self._skill_read_path(request)
        if skill_path is not None and self._should_single_read_skill_path(skill_path):
            if skill_path in self._seen_single_read_skill_paths:
                return self._blocked_duplicate_skill_read_response(request, skill_path)
            result = handler(request)
            self._seen_single_read_skill_paths.add(skill_path)
            return result

        payload = self._payload_for_request(request)
        if payload is None:
            if (
                self._is_hypothesis_report_save_request(request)
                and self._save_attempt_limit_reached()
            ):
                self._hypothesis_stop_requested = True
                return self._blocked_after_attempt_limit_response(request)
            result = handler(request)
            self._record_save_attempt(request)
            self._record_hypothesis_save_result(request)
            if (
                self._is_hypothesis_report_save_request(request)
                and self._save_attempt_limit_reached()
            ):
                self._hypothesis_stop_requested = True
            return result
        if self._stop_after_first_save and self._hypothesis_save_seen:
            return self._blocked_after_save_response(request)
        if self._save_attempt_limit_reached():
            self._hypothesis_stop_requested = True
            return self._blocked_after_attempt_limit_response(request)
        payload_hash = canonical_json_hash(payload)
        if payload_hash in self._rejected_payload_hashes:
            return self._blocked_response(request, payload_hash)
        result = handler(request)
        self._record_save_attempt(request)
        self._record_hypothesis_save_result(request)
        self._record_if_rejected(payload_hash, result)
        if self._save_attempt_limit_reached():
            self._hypothesis_stop_requested = True
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        skill_path = self._skill_read_path(request)
        if skill_path is not None and self._should_single_read_skill_path(skill_path):
            if skill_path in self._seen_single_read_skill_paths:
                return self._blocked_duplicate_skill_read_response(request, skill_path)
            result = await handler(request)
            self._seen_single_read_skill_paths.add(skill_path)
            return result

        payload = self._payload_for_request(request)
        if payload is None:
            if (
                self._is_hypothesis_report_save_request(request)
                and self._save_attempt_limit_reached()
            ):
                self._hypothesis_stop_requested = True
                return self._blocked_after_attempt_limit_response(request)
            result = await handler(request)
            self._record_save_attempt(request)
            self._record_hypothesis_save_result(request)
            if (
                self._is_hypothesis_report_save_request(request)
                and self._save_attempt_limit_reached()
            ):
                self._hypothesis_stop_requested = True
            return result
        if self._stop_after_first_save and self._hypothesis_save_seen:
            return self._blocked_after_save_response(request)
        if self._save_attempt_limit_reached():
            self._hypothesis_stop_requested = True
            return self._blocked_after_attempt_limit_response(request)
        payload_hash = canonical_json_hash(payload)
        if payload_hash in self._rejected_payload_hashes:
            return self._blocked_response(request, payload_hash)
        result = await handler(request)
        self._record_save_attempt(request)
        self._record_hypothesis_save_result(request)
        self._record_if_rejected(payload_hash, result)
        if self._save_attempt_limit_reached():
            self._hypothesis_stop_requested = True
        return result
