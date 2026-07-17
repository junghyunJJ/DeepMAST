"""Tests for hypothesis writer retry-loop middleware controls."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage

from src.agents.drug_target.middleware import HypothesisRetryLoopMiddleware


def _save_request(
    call_id: str = "call-1", report: dict[str, Any] | None = None
) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={
            "name": "save_hypothesis_report",
            "args": {"report": report or {"hypotheses": []}},
            "id": call_id,
            "type": "tool_call",
        },
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )


def _sections_save_request(call_id: str = "sections-1") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={
            "name": "save_report_sections",
            "args": {"payload": {"schema_version": "hybrid_report_sections/v1"}},
            "id": call_id,
            "type": "tool_call",
        },
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )


def _read_skill_request(
    call_id: str = "skill-call-1",
    skill_path: str = "skills/drug-target-hypothesis/SKILL.md",
) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={
            "name": "read_skill_file",
            "args": {"skill_path": skill_path},
            "id": call_id,
            "type": "tool_call",
        },
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )


def test_stop_after_first_save_requests_end_after_model() -> None:
    middleware = HypothesisRetryLoopMiddleware(stop_after_first_save=True)
    request = _save_request()

    def handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=json.dumps({"saved": False}),
            tool_call_id=req.tool_call["id"],
        )

    result = middleware.wrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert middleware.after_model({}, None) == {"jump_to": "end"}  # type: ignore[arg-type]
    assert middleware.after_model({}, None) is None  # type: ignore[arg-type]


def test_terminal_save_tool_requests_end_after_first_sections_save() -> None:
    middleware = HypothesisRetryLoopMiddleware(
        stop_after_first_save=True,
        terminal_save_tool_names=("save_report_sections",),
    )

    def handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=json.dumps({"saved": False}),
            tool_call_id=req.tool_call["id"],
        )

    middleware.wrap_tool_call(_sections_save_request(), handler)

    assert middleware.after_model({}, None) == {"jump_to": "end"}  # type: ignore[arg-type]


def test_success_only_terminal_save_retries_failed_sections_save_once() -> None:
    middleware = HypothesisRetryLoopMiddleware(
        stop_after_first_save=True,
        stop_after_first_successful_save=True,
        terminal_save_tool_names=("save_report_sections",),
        max_hypothesis_save_attempts=2,
    )
    receipts = iter((False, True))

    def handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=json.dumps({"saved": next(receipts), "errors": ["score"]}),
            tool_call_id=req.tool_call["id"],
        )

    middleware.wrap_tool_call(_sections_save_request("sections-1"), handler)
    assert middleware.after_model({}, None) is None  # type: ignore[arg-type]

    middleware.wrap_tool_call(_sections_save_request("sections-2"), handler)
    assert middleware.after_model({}, None) == {"jump_to": "end"}  # type: ignore[arg-type]


def test_success_only_terminal_save_ends_after_second_failed_sections_save() -> None:
    middleware = HypothesisRetryLoopMiddleware(
        stop_after_first_save=True,
        stop_after_first_successful_save=True,
        terminal_save_tool_names=("save_report_sections",),
        max_hypothesis_save_attempts=2,
    )

    def handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=json.dumps({"saved": False, "errors": ["score"]}),
            tool_call_id=req.tool_call["id"],
        )

    middleware.wrap_tool_call(_sections_save_request("sections-1"), handler)
    assert middleware.after_model({}, None) is None  # type: ignore[arg-type]

    middleware.wrap_tool_call(_sections_save_request("sections-2"), handler)
    assert middleware.after_model({}, None) == {"jump_to": "end"}  # type: ignore[arg-type]


def test_stop_after_first_save_blocks_additional_save_calls() -> None:
    middleware = HypothesisRetryLoopMiddleware(stop_after_first_save=True)
    first = _save_request("call-1")
    second = _save_request("call-2")

    def handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=json.dumps({"saved": False}),
            tool_call_id=req.tool_call["id"],
        )

    middleware.wrap_tool_call(first, handler)
    blocked = middleware.wrap_tool_call(second, handler)
    payload = json.loads(str(blocked.content))

    assert payload["saved"] is False
    assert "graph-native hypothesis quality retry" in payload["error"]


def test_async_stop_after_first_save_requests_end_after_model() -> None:
    async def run() -> dict[str, Any] | None:
        middleware = HypothesisRetryLoopMiddleware(stop_after_first_save=True)
        request = _save_request()

        async def handler(req: ToolCallRequest) -> ToolMessage:
            return ToolMessage(
                content=json.dumps({"saved": False}),
                tool_call_id=req.tool_call["id"],
            )

        await middleware.awrap_tool_call(request, handler)
        return await middleware.aafter_model({}, None)  # type: ignore[arg-type]

    assert asyncio.run(run()) == {"jump_to": "end"}


def test_default_middleware_does_not_stop_after_save() -> None:
    middleware = HypothesisRetryLoopMiddleware()
    request = _save_request()

    def handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=json.dumps({"saved": False}),
            tool_call_id=req.tool_call["id"],
        )

    middleware.wrap_tool_call(request, handler)

    assert middleware.after_model({}, None) is None  # type: ignore[arg-type]


def test_save_attempt_limit_requests_end_after_last_failed_attempt() -> None:
    middleware = HypothesisRetryLoopMiddleware(max_hypothesis_save_attempts=2)

    def handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=json.dumps({"saved": False}),
            tool_call_id=req.tool_call["id"],
        )

    middleware.wrap_tool_call(
        _save_request("call-1", {"hypotheses": [{"id": 1}]}),
        handler,
    )
    assert middleware.after_model({}, None) is None  # type: ignore[arg-type]

    middleware.wrap_tool_call(
        _save_request("call-2", {"hypotheses": [{"id": 2}]}),
        handler,
    )
    assert middleware.after_model({}, None) == {"jump_to": "end"}  # type: ignore[arg-type]


def test_save_attempt_limit_blocks_extra_save_calls() -> None:
    middleware = HypothesisRetryLoopMiddleware(max_hypothesis_save_attempts=1)

    def handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=json.dumps({"saved": True}),
            tool_call_id=req.tool_call["id"],
        )

    middleware.wrap_tool_call(
        _save_request("call-1", {"hypotheses": [{"id": 1}]}),
        handler,
    )
    blocked = middleware.wrap_tool_call(
        _save_request("call-2", {"hypotheses": [{"id": 2}]}),
        handler,
    )
    payload = json.loads(str(blocked.content))

    assert payload["saved"] is False
    assert payload["attempts"] == 1
    assert payload["max_attempts"] == 1
    assert "save attempt limit reached" in payload["error"]


def test_single_read_skill_path_blocks_duplicate_sync_tool_call() -> None:
    middleware = HypothesisRetryLoopMiddleware(
        single_read_skill_paths=("skills/drug-target-hypothesis/SKILL.md",)
    )
    handler_calls: list[str] = []

    def handler(req: ToolCallRequest) -> ToolMessage:
        handler_calls.append(str(req.tool_call["id"]))
        return ToolMessage(
            content="DTH SKILL CONTENT",
            tool_call_id=req.tool_call["id"],
        )

    first = middleware.wrap_tool_call(_read_skill_request("call-1"), handler)
    second = middleware.wrap_tool_call(_read_skill_request("call-2"), handler)

    assert str(first.content) == "DTH SKILL CONTENT"
    assert handler_calls == ["call-1"]
    assert "already loaded earlier" in str(second.content)
    assert "skills/drug-target-hypothesis/SKILL.md" in str(second.content)


def test_single_read_skill_path_allows_retry_after_sync_handler_exception() -> None:
    middleware = HypothesisRetryLoopMiddleware(
        single_read_skill_paths=("skills/drug-target-hypothesis/SKILL.md",)
    )
    handler_calls: list[str] = []

    def handler(req: ToolCallRequest) -> ToolMessage:
        handler_calls.append(str(req.tool_call["id"]))
        if len(handler_calls) == 1:
            raise RuntimeError("transient read failure")
        return ToolMessage(
            content="DTH SKILL CONTENT",
            tool_call_id=req.tool_call["id"],
        )

    try:
        middleware.wrap_tool_call(_read_skill_request("call-1"), handler)
    except RuntimeError as exc:
        assert str(exc) == "transient read failure"
    else:
        raise AssertionError("expected transient read failure")

    second = middleware.wrap_tool_call(_read_skill_request("call-2"), handler)

    assert str(second.content) == "DTH SKILL CONTENT"
    assert handler_calls == ["call-1", "call-2"]


def test_single_read_skill_path_blocks_duplicate_async_tool_call() -> None:
    async def run() -> tuple[str, str, list[str]]:
        middleware = HypothesisRetryLoopMiddleware(
            single_read_skill_paths=("skills/drug-target-hypothesis/SKILL.md",)
        )
        handler_calls: list[str] = []

        async def handler(req: ToolCallRequest) -> ToolMessage:
            handler_calls.append(str(req.tool_call["id"]))
            return ToolMessage(
                content="DTH SKILL CONTENT",
                tool_call_id=req.tool_call["id"],
            )

        first = await middleware.awrap_tool_call(
            _read_skill_request("call-1"),
            handler,
        )
        second = await middleware.awrap_tool_call(
            _read_skill_request("call-2"),
            handler,
        )
        return str(first.content), str(second.content), handler_calls

    first_content, second_content, handler_calls = asyncio.run(run())

    assert first_content == "DTH SKILL CONTENT"
    assert handler_calls == ["call-1"]
    assert "already loaded earlier" in second_content


def test_single_read_skill_path_allows_retry_after_async_handler_exception() -> None:
    async def run() -> tuple[str, list[str]]:
        middleware = HypothesisRetryLoopMiddleware(
            single_read_skill_paths=("skills/drug-target-hypothesis/SKILL.md",)
        )
        handler_calls: list[str] = []

        async def handler(req: ToolCallRequest) -> ToolMessage:
            handler_calls.append(str(req.tool_call["id"]))
            if len(handler_calls) == 1:
                raise RuntimeError("transient read failure")
            return ToolMessage(
                content="DTH SKILL CONTENT",
                tool_call_id=req.tool_call["id"],
            )

        try:
            await middleware.awrap_tool_call(_read_skill_request("call-1"), handler)
        except RuntimeError as exc:
            assert str(exc) == "transient read failure"
        else:
            raise AssertionError("expected transient read failure")

        second = await middleware.awrap_tool_call(_read_skill_request("call-2"), handler)
        return str(second.content), handler_calls

    second_content, handler_calls = asyncio.run(run())

    assert second_content == "DTH SKILL CONTENT"
    assert handler_calls == ["call-1", "call-2"]


def test_single_read_skill_path_does_not_block_unconfigured_skill() -> None:
    middleware = HypothesisRetryLoopMiddleware(
        single_read_skill_paths=("skills/drug-target-hypothesis/SKILL.md",)
    )
    handler_calls: list[str] = []

    def handler(req: ToolCallRequest) -> ToolMessage:
        handler_calls.append(str(req.tool_call["id"]))
        return ToolMessage(
            content="STRING SKILL CONTENT",
            tool_call_id=req.tool_call["id"],
        )

    first = middleware.wrap_tool_call(
        _read_skill_request("call-1", "skills/string-database/SKILL.md"),
        handler,
    )
    second = middleware.wrap_tool_call(
        _read_skill_request("call-2", "skills/string-database/SKILL.md"),
        handler,
    )

    assert str(first.content) == "STRING SKILL CONTENT"
    assert str(second.content) == "STRING SKILL CONTENT"
    assert handler_calls == ["call-1", "call-2"]
