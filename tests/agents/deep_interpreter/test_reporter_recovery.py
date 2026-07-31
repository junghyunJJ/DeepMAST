from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from langchain_core.messages import ToolCall, ToolMessage
from langchain.tools.tool_node import ToolCallRequest

from src.agents.deep_interpreter.reporter_recovery import (
    DEFAULT_REPORTER_ATTEMPT_TIMEOUT_SECONDS,
    ReporterRecoveryError,
    ReporterTaskRecoveryMiddleware,
    inspect_reporter_completion,
    reporter_attempt_timeout_seconds,
    run_reporter_with_recovery,
)


def _write_reporter_outputs(data_dir: Path, *, status: str, errors: int) -> None:
    (data_dir / "synthesis.md").write_text(
        "# Synthesis\n\n## Executive Summary\n\nGrounded narrative.\n",
        encoding="utf-8",
    )
    (data_dir / "synthesis_validation.json").write_text(
        json.dumps(
            {
                "synthesis_guardrail": {
                    "status": status,
                    "final_error_count": errors,
                }
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "synthesis_targets.json").write_text("{}", encoding="utf-8")
    (data_dir / "CCI_Analysis_Report.html").write_text(
        "<html>report</html>",
        encoding="utf-8",
    )


def test_reporter_attempt_timeout_seconds_accepts_positive_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPORTER_ATTEMPT_TIMEOUT_SECONDS", "12.5")

    assert reporter_attempt_timeout_seconds() == 12.5


@pytest.mark.parametrize("value", ["nan", "inf"])
def test_reporter_attempt_timeout_seconds_rejects_non_finite_override(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("REPORTER_ATTEMPT_TIMEOUT_SECONDS", value)

    assert (
        reporter_attempt_timeout_seconds()
        == DEFAULT_REPORTER_ATTEMPT_TIMEOUT_SECONDS
    )


def test_inspect_reporter_completion_requires_guardrail_pass(tmp_path: Path) -> None:
    _write_reporter_outputs(tmp_path, status="failed", errors=1)

    result = inspect_reporter_completion(tmp_path)

    assert result["complete"] is False
    assert result["guardrail_status"] == "failed"
    assert result["final_error_count"] == 1


def test_inspect_reporter_completion_accepts_complete_pass(tmp_path: Path) -> None:
    _write_reporter_outputs(tmp_path, status="passed", errors=0)

    result = inspect_reporter_completion(tmp_path)

    assert result["complete"] is True
    assert result["missing_outputs"] == []


def test_deep_interpreter_agent_attaches_reporter_recovery_middleware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.agent import (
        DeepInterpreterConfig,
        create_deep_interpreter_agent,
    )

    created: dict[str, object] = {}

    def fake_create_deep_agent(**kwargs: object) -> SimpleNamespace:
        created.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setenv("REPORTER_ATTEMPT_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setattr(
        "src.agents.deep_interpreter.agent.create_llm",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "src.agents.deep_interpreter.agent.create_deep_agent",
        fake_create_deep_agent,
    )

    create_deep_interpreter_agent(
        DeepInterpreterConfig(provider="ollama", data_dir=str(tmp_path))
    )

    middleware = created["middleware"]
    assert isinstance(middleware, list)
    reporter_recovery = [
        item for item in middleware if isinstance(item, ReporterTaskRecoveryMiddleware)
    ]
    assert len(reporter_recovery) == 1
    assert reporter_recovery[0]._data_dir == tmp_path.resolve()
    assert reporter_recovery[0]._timeout_seconds == 12.5


@pytest.mark.asyncio
async def test_reporter_task_recovery_middleware_intercepts_only_reporter_task(
    tmp_path: Path,
) -> None:
    middleware = ReporterTaskRecoveryMiddleware(data_dir=tmp_path, timeout_seconds=1)
    seen_calls: list[ToolCall] = []
    reporter_attempts = 0
    runtime = cast(Any, None)

    async def handler(request: ToolCallRequest) -> ToolMessage:
        nonlocal reporter_attempts
        seen_calls.append(request.tool_call)
        args = request.tool_call.get("args")
        if isinstance(args, dict) and args.get("subagent_type") == "reporter":
            reporter_attempts += 1
        if reporter_attempts == 2:
            _write_reporter_outputs(tmp_path, status="passed", errors=0)
        return ToolMessage(
            content=f"attempt-{len(seen_calls)}",
            tool_call_id=str(request.tool_call["id"]),
        )

    non_reporter = ToolCallRequest(
        tool_call={
            "name": "task",
            "args": {"subagent_type": "interpreter", "description": "interpret"},
            "id": "call-interpreter",
            "type": "tool_call",
        },
        tool=None,
        state={},
        runtime=runtime,
    )
    result = await middleware.awrap_tool_call(non_reporter, handler)

    assert isinstance(result, ToolMessage)
    assert result.content == "attempt-1"
    assert len(seen_calls) == 1
    assert not (tmp_path / "reporter_recovery.json").exists()

    reporter = ToolCallRequest(
        tool_call={
            "name": "task",
            "args": {"subagent_type": "reporter", "description": "report"},
            "id": "call-reporter",
            "type": "tool_call",
        },
        tool=None,
        state={},
        runtime=runtime,
    )
    result = await middleware.awrap_tool_call(reporter, handler)

    assert isinstance(result, ToolMessage)
    assert result.content == "attempt-3"
    assert len(seen_calls) == 3
    first_reporter_args = seen_calls[1]["args"]
    second_reporter_args = seen_calls[2]["args"]
    assert isinstance(first_reporter_args, dict)
    assert isinstance(second_reporter_args, dict)
    assert first_reporter_args["description"] == "report"
    assert second_reporter_args["description"].startswith("[REPORTER_RECOVERY]")
    assert seen_calls[2]["id"] == "call-reporter"
    assert second_reporter_args["subagent_type"] == "reporter"


@pytest.mark.asyncio
async def test_reporter_recovery_uses_fresh_context_once(tmp_path: Path) -> None:
    prompts: list[str] = []

    async def invoke(description: str) -> dict[str, list[dict[str, str]]]:
        prompts.append(description)
        if len(prompts) == 1:
            (tmp_path / "synthesis.md").write_text(
                "<p>Unsupported fragment</p>",
                encoding="utf-8",
            )
            (tmp_path / "synthesis_validation.json").write_text(
                json.dumps(
                    {
                        "synthesis_guardrail": {
                            "status": "failed",
                            "final_error_count": 1,
                        }
                    }
                ),
                encoding="utf-8",
            )
        else:
            _write_reporter_outputs(tmp_path, status="passed", errors=0)
        return {
            "messages": [
                {"role": "assistant", "content": f"attempt-{len(prompts)}"}
            ]
        }

    result = await run_reporter_with_recovery(
        invoke=invoke,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert result["messages"][-1]["content"] == "attempt-2"
    assert prompts[0] == "normal reporter request"
    assert prompts[1].startswith("[REPORTER_RECOVERY]")
    assert "tool results above" not in prompts[1]
    assert "prepare_rag_literature" in prompts[1]
    assert (tmp_path / "synthesis_reporter_attempt1.md").read_text(
        encoding="utf-8"
    ) == "<p>Unsupported fragment</p>"
    audit = json.loads((tmp_path / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert audit["status"] == "passed"
    assert audit["attempt_count"] == 2
    assert audit["recovery_used"] is True


@pytest.mark.asyncio
async def test_reporter_recovery_retries_once_after_timeout(tmp_path: Path) -> None:
    prompts: list[str] = []
    never_finishes = asyncio.Event()

    async def invoke(description: str) -> dict[str, list[dict[str, str]]]:
        prompts.append(description)
        if len(prompts) == 1:
            await never_finishes.wait()
        _write_reporter_outputs(tmp_path, status="passed", errors=0)
        return {
            "messages": [
                {"role": "assistant", "content": f"attempt-{len(prompts)}"}
            ]
        }

    result = await run_reporter_with_recovery(
        invoke=invoke,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=0.01,
    )

    assert result["messages"][-1]["content"] == "attempt-2"
    assert len(prompts) == 2
    audit = json.loads((tmp_path / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert audit["status"] == "passed"
    assert audit["attempts"][0]["timed_out"] is True
    assert audit["recovery_used"] is True


@pytest.mark.asyncio
async def test_reporter_recovery_retries_when_first_attempt_leaves_stale_outputs(
    tmp_path: Path,
) -> None:
    _write_reporter_outputs(tmp_path, status="passed", errors=0)
    prompts: list[str] = []

    async def invoke(description: str) -> dict[str, list[dict[str, str]]]:
        prompts.append(description)
        if len(prompts) == 2:
            _write_reporter_outputs(tmp_path, status="passed", errors=0)
        return {"messages": [{"role": "assistant", "content": "done"}]}

    await run_reporter_with_recovery(
        invoke=invoke,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert len(prompts) == 2
    assert prompts[1].startswith("[REPORTER_RECOVERY]")


def test_reporter_task_recovery_middleware_times_out_sync_reporter(
    tmp_path: Path,
) -> None:
    middleware = ReporterTaskRecoveryMiddleware(data_dir=tmp_path, timeout_seconds=0.01)
    attempts = 0
    request = ToolCallRequest(
        tool_call={
            "name": "task",
            "args": {"subagent_type": "reporter", "description": "report"},
            "id": "call-reporter",
            "type": "tool_call",
        },
        tool=None,
        state={},
        runtime=cast(Any, None),
    )

    def handler(_request: ToolCallRequest) -> ToolMessage:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            time.sleep(0.2)
        else:
            _write_reporter_outputs(tmp_path, status="passed", errors=0)
        return ToolMessage(content="done", tool_call_id="call-reporter")

    started = time.monotonic()
    result = middleware.wrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert attempts == 2
    assert time.monotonic() - started < 0.1


@pytest.mark.asyncio
async def test_reporter_recovery_raises_after_second_invalid_attempt(
    tmp_path: Path,
) -> None:
    prompts: list[str] = []

    async def invoke(description: str) -> dict[str, list[dict[str, str]]]:
        prompts.append(description)
        _write_reporter_outputs(tmp_path, status="failed", errors=1)
        return {
            "messages": [
                {"role": "assistant", "content": f"attempt-{len(prompts)}"}
            ]
        }

    with pytest.raises(ReporterRecoveryError):
        await run_reporter_with_recovery(
            invoke=invoke,
            initial_description="normal reporter request",
            data_dir=tmp_path,
            timeout_seconds=1,
        )

    assert len(prompts) == 2
    audit = json.loads((tmp_path / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert audit["status"] == "failed"
    assert audit["attempt_count"] == 2
    assert audit["recovery_used"] is True
