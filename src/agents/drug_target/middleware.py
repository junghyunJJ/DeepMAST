"""Middleware for the drug_target agent package.

Retained from the 2026-05-13 summarizer simplification.
``HypothesisRetryLoopMiddleware`` is out of scope for the
summarizer→finalize_report migration (used by hypothesis_writer to suppress
identical-payload retries against the deterministic save gate).
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Awaitable, Callable, Collection, Sequence
from pathlib import Path
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import hook_config
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, ToolCall, ToolMessage
from langgraph.types import Command

from src.agents.drug_target.report_guardrails import run_drug_report_guardrail
from src.agents.drug_target.hybrid_report_sections import REPORT_SECTIONS_FILENAME
from src.agents.drug_target.tools.report_expansion_schema import canonical_json_hash


_HYBRID_PREPUBLICATION_ARTIFACTS = (
    REPORT_SECTIONS_FILENAME,
    "report_data.json",
    "drug_report_render.json",
)


def clear_guarded_report_run_artifacts(data_dir: str | Path) -> None:
    """Remove guarded-run outputs while preserving evidence inputs."""
    from src.agents.drug_target.report_guardrails import (
        _resolve_safe_run_dir,
        clear_derived_report_artifacts,
    )

    run_dir = _resolve_safe_run_dir(data_dir)
    clear_derived_report_artifacts(
        run_dir,
        include_audits=True,
        include_sources=True,
    )
    for name in _HYBRID_PREPUBLICATION_ARTIFACTS:
        path = run_dir / name
        for candidate in (path, path.with_suffix(f"{path.suffix}.tmp")):
            candidate.unlink(missing_ok=True)
    for staging_dir in run_dir.glob(".report-sections-*"):
        if staging_dir.is_dir() and not staging_dir.is_symlink():
            shutil.rmtree(staging_dir)
        else:
            staging_dir.unlink(missing_ok=True)


class _DrugReportRunDirectoryMiddleware(AgentMiddleware):
    """Shared fail-closed run-directory cleanup boundary."""

    def __init__(self, data_dir: str | Path | None) -> None:
        super().__init__()
        self._data_dir = Path(data_dir).expanduser() if data_dir is not None else None

    def _require_data_dir(self) -> Path:
        if self._data_dir is None:
            raise RuntimeError("Drug report guardrail requires an explicit data_dir")
        from src.agents.drug_target.report_guardrails import _resolve_safe_run_dir

        return _resolve_safe_run_dir(self._data_dir)

    def _clear_for_new_run(self) -> None:
        clear_guarded_report_run_artifacts(self._require_data_dir())

    def before_agent(self, state: Any, runtime: Any) -> None:
        self._clear_for_new_run()
        return None

    async def abefore_agent(self, state: Any, runtime: Any) -> None:
        await asyncio.to_thread(self._clear_for_new_run)
        return None


class DrugReportRunCleanupMiddleware(_DrugReportRunDirectoryMiddleware):
    """Clear stale guarded-run artifacts before top-level orchestration begins."""


class DrugReportGuardrailMiddleware(_DrugReportRunDirectoryMiddleware):
    """Validate/repair/publish only after a report-writer invocation completes."""

    def __init__(
        self,
        data_dir: str | Path | None,
        *,
        provider: str | None = None,
        model: str | None = None,
        request_timeout_seconds: float | None = None,
        disease: str = "",
    ) -> None:
        super().__init__(data_dir)
        self._provider = provider
        self._model = model
        self._request_timeout_seconds = request_timeout_seconds
        self._disease = disease

    def _run(self) -> dict[str, Any]:
        data_dir = self._require_data_dir()
        guardrail_kwargs: dict[str, Any] = {
            "provider": self._provider,
            "disease": self._disease,
            "require_report_sections": True,
        }
        if self._model:
            guardrail_kwargs["model"] = self._model
        if self._request_timeout_seconds is not None:
            guardrail_kwargs["request_timeout_seconds"] = self._request_timeout_seconds
        result = run_drug_report_guardrail(data_dir, **guardrail_kwargs)
        if result.get("status") == "failed":
            final_error_count = result.get("final_error_count", "unknown")
            detail = result.get("publication_error") or f"{final_error_count} hard error(s)"
            raise RuntimeError(
                "Drug report guardrail failed with "
                f"{detail}; see {data_dir / 'drug_report_validation_final.json'}"
            )
        return {
            "messages": [
                AIMessage(
                    content=json.dumps(
                        {"drug_report_guardrail": result},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            ]
        }

    def after_agent(self, state: Any, runtime: Any) -> dict[str, Any]:
        return self._run()

    async def aafter_agent(self, state: Any, runtime: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._run)


class DrugTargetManagedFilesystemGuardMiddleware(AgentMiddleware):
    """Block generic content tools and bind domain tools to one run directory."""

    _BLOCKED_TOOL_NAMES = frozenset({"read_file", "grep", "write_file", "edit_file", "execute"})

    def __init__(
        self,
        data_dir: str | Path,
        *,
        data_dir_tool_names: Collection[str],
    ) -> None:
        super().__init__()
        from src.agents.drug_target.report_guardrails import _resolve_safe_run_dir

        self._data_dir = _resolve_safe_run_dir(data_dir)
        self._data_dir_tool_names = frozenset(data_dir_tool_names)

    @staticmethod
    def _blocked_response(request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=(
                f"ERROR: {request.tool_call.get('name', 'tool')} is blocked in the "
                "managed Drug Target filesystem. Use an allowed domain tool instead."
            ),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def _patched_request(self, request: ToolCallRequest) -> ToolCallRequest:
        tool_call = request.tool_call
        if tool_call.get("name") not in self._data_dir_tool_names:
            return request
        args = tool_call.get("args")
        patched_args = {**args, "data_dir": str(self._data_dir)} if isinstance(args, dict) else {"data_dir": str(self._data_dir)}
        patched_call = cast(ToolCall, {**tool_call, "args": patched_args})
        return request.override(tool_call=patched_call)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") in self._BLOCKED_TOOL_NAMES:
            return self._blocked_response(request)
        return handler(self._patched_request(request))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") in self._BLOCKED_TOOL_NAMES:
            return self._blocked_response(request)
        return await handler(self._patched_request(request))


class DrugTargetTaskAllowlistMiddleware(AgentMiddleware):
    """Keep production orchestration to its two explicit domain subagents."""

    _PRODUCTION_SUBAGENT_TYPES = frozenset({"evidence_assessor", "report_writer"})

    def __init__(self, allowed_subagent_types: Collection[str]) -> None:
        super().__init__()
        self._allowed_subagent_types = (
            frozenset(allowed_subagent_types) & self._PRODUCTION_SUBAGENT_TYPES
        )

    def _is_allowed(self, request: ToolCallRequest) -> bool:
        if request.tool_call.get("name") != "task":
            return True
        args = request.tool_call.get("args")
        return isinstance(args, dict) and args.get("subagent_type") in self._allowed_subagent_types

    @staticmethod
    def _blocked_response(request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=(
                "ERROR: task subagent_type is not allowed for guarded Drug Target "
                "production. Allowed types: evidence_assessor, report_writer."
            ),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if not self._is_allowed(request):
            return self._blocked_response(request)
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if not self._is_allowed(request):
            return self._blocked_response(request)
        return await handler(request)


class HypothesisRetryLoopMiddleware(AgentMiddleware):
    """Block unchanged retries after a deterministic hypothesis-save rejection.

    Used by the ``hypothesis_writer`` subagent. Out of scope for the
    2026-05-13 summarizer simplification.
    """

    def __init__(
        self,
        *,
        stop_after_first_save: bool = False,
        stop_after_first_successful_save: bool = False,
        terminal_save_tool_names: Sequence[str] = (),
        max_hypothesis_save_attempts: int | None = None,
        single_read_skill_paths: Sequence[str] = (),
    ) -> None:
        super().__init__()
        self._stop_after_first_save = stop_after_first_save
        self._stop_after_first_successful_save = stop_after_first_successful_save
        self._terminal_save_tool_names = tuple(terminal_save_tool_names)
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
        if tool_name in self._terminal_save_tool_names:
            return True
        if tool_name == "save_hypothesis_report":
            return True
        args = request.tool_call.get("args") or {}
        return (
            tool_name == "save_evidence"
            and isinstance(args, dict)
            and args.get("filename") == "hypothesis_report.json"
        )

    def _record_hypothesis_save_result(
        self, request: ToolCallRequest, result: ToolMessage | Command
    ) -> None:
        if not self._stop_after_first_save:
            return
        if not self._is_hypothesis_report_save_request(request):
            return
        if self._stop_after_first_successful_save and self._result_saved_false(result):
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
            self._record_hypothesis_save_result(request, result)
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
        self._record_hypothesis_save_result(request, result)
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
            self._record_hypothesis_save_result(request, result)
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
        self._record_hypothesis_save_result(request, result)
        self._record_if_rejected(payload_hash, result)
        if self._save_attempt_limit_reached():
            self._hypothesis_stop_requested = True
        return result
