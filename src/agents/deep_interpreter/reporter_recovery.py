from __future__ import annotations

import asyncio
import concurrent.futures
import json
import math
import os
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar, cast

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolCall, ToolMessage
from langgraph.types import Command

REPORTER_OUTPUTS = (
    "synthesis.md",
    "synthesis_validation.json",
    "synthesis_targets.json",
    "CCI_Analysis_Report.html",
)
DEFAULT_REPORTER_ATTEMPT_TIMEOUT_SECONDS = 3600.0
MAX_REPORTER_ATTEMPTS = 2

_REPORTER_TIMEOUT_ENV = "REPORTER_ATTEMPT_TIMEOUT_SECONDS"

T = TypeVar("T")


class ReporterRecoveryError(RuntimeError):
    pass


def reporter_attempt_timeout_seconds() -> float:
    try:
        timeout = float(
            os.getenv(
                _REPORTER_TIMEOUT_ENV,
                str(DEFAULT_REPORTER_ATTEMPT_TIMEOUT_SECONDS),
            )
        )
    except ValueError:
        return DEFAULT_REPORTER_ATTEMPT_TIMEOUT_SECONDS
    if not math.isfinite(timeout) or timeout <= 0:
        return DEFAULT_REPORTER_ATTEMPT_TIMEOUT_SECONDS
    return timeout


def _reporter_output_state(data_dir: Path) -> dict[str, tuple[int, int]]:
    return {
        name: ((data_dir / name).stat().st_mtime_ns, (data_dir / name).stat().st_size)
        for name in REPORTER_OUTPUTS
        if (data_dir / name).is_file()
    }


def inspect_reporter_completion(
    data_dir: str | Path,
    previous_state: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    root = Path(data_dir)
    missing_outputs = [
        name
        for name in REPORTER_OUTPUTS
        if not (root / name).is_file() or (root / name).stat().st_size == 0
    ]

    validation_path = root / "synthesis_validation.json"
    validation: dict[str, Any] = {}
    parse_error: str | None = None
    if validation_path.is_file() and validation_path.stat().st_size > 0:
        try:
            loaded = json.loads(validation_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                validation = loaded
        except json.JSONDecodeError as exc:
            parse_error = str(exc)

    guardrail = validation.get("synthesis_guardrail")
    if not isinstance(guardrail, dict):
        guardrail = {}
    status = guardrail.get("status")
    final_error_count = guardrail.get("final_error_count")
    current_state = _reporter_output_state(root)
    stale_outputs = [
        name
        for name, state in (previous_state or {}).items()
        if current_state.get(name) == state
    ]

    complete = (
        not missing_outputs
        and not stale_outputs
        and status == "passed"
        and final_error_count == 0
    )
    return {
        "complete": complete,
        "missing_outputs": missing_outputs,
        "guardrail_status": status,
        "final_error_count": final_error_count,
        "validation_parse_error": parse_error,
        "stale_outputs": stale_outputs,
    }


def build_reporter_recovery_message(data_dir: Path) -> str:
    return f"""[REPORTER_RECOVERY]
The previous REPORTER attempt for {data_dir} timed out or produced an invalid report.
Start from a fresh message context and rebuild the final synthesis from the existing artifacts.

Read /part1_final.md, /part2_final.md, /part3_final.md,
/part4_therapeutic_synthesis.md when present, /drug.md when present, and /papers.json.
Use only the already-bound part_name="all" RAG collection.
Do not call prepare_rag_literature.
Do not run a new literature search, create a collection, or create reporter-specific paper artifacts.
Write a complete Markdown document to /synthesis.md. It must start with a Markdown title,
contain substantive ## sections, and contain no HTML fragment in place of the report.
Then call generate_html_report once with template_mode="comprehensive",
output_path="CCI_Analysis_Report.html", and the data directory from /data_path.txt.
Stop after generate_html_report returns.
"""


def _audit_path(data_dir: Path) -> Path:
    return data_dir / "reporter_recovery.json"


def _write_audit(data_dir: Path, audit: dict[str, Any]) -> None:
    _audit_path(data_dir).write_text(
        json.dumps(audit, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _copy_first_synthesis(data_dir: Path) -> None:
    source = data_dir / "synthesis.md"
    if source.is_file():
        shutil.copyfile(source, data_dir / "synthesis_reporter_attempt1.md")


async def run_reporter_with_recovery(
    *,
    invoke: Callable[[str], Awaitable[T]],
    initial_description: str,
    data_dir: str | Path,
    timeout_seconds: float | None = None,
) -> T:
    root = Path(data_dir)
    timeout = timeout_seconds if timeout_seconds is not None else reporter_attempt_timeout_seconds()
    audit: dict[str, Any] = {
        "status": "running",
        "attempt_count": 0,
        "recovery_used": False,
        "attempts": [],
    }

    for attempt_number in range(1, MAX_REPORTER_ATTEMPTS + 1):
        description = (
            initial_description
            if attempt_number == 1
            else build_reporter_recovery_message(root)
        )
        started = time.monotonic()
        attempt: dict[str, Any] = {
            "attempt": attempt_number,
            "timed_out": False,
        }
        previous_state = _reporter_output_state(root)
        try:
            result = await asyncio.wait_for(invoke(description), timeout=timeout)
        except TimeoutError:
            attempt["timed_out"] = True
            attempt["duration_seconds"] = time.monotonic() - started
            attempt["completion"] = inspect_reporter_completion(root, previous_state)
            cast(list[dict[str, Any]], audit["attempts"]).append(attempt)
            audit["attempt_count"] = attempt_number
        else:
            attempt["duration_seconds"] = time.monotonic() - started
            attempt["completion"] = inspect_reporter_completion(root, previous_state)
            cast(list[dict[str, Any]], audit["attempts"]).append(attempt)
            audit["attempt_count"] = attempt_number
            if attempt["completion"]["complete"]:
                audit["status"] = "passed"
                _write_audit(root, audit)
                return result

        if attempt_number == 1:
            audit["recovery_used"] = True
            _copy_first_synthesis(root)
            continue

        audit["status"] = "failed"
        _write_audit(root, audit)
        raise ReporterRecoveryError("REPORTER failed after two attempts.")

    raise ReporterRecoveryError("REPORTER recovery loop exited unexpectedly.")


def _first_user_message_text(state: Any) -> str:
    if not isinstance(state, dict):
        return ""
    messages = state.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in messages:
        if isinstance(message, BaseMessage):
            if message.type == "human":
                return str(message.content)
            continue
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def wrap_reporter_runnable(
    agent: Any,
    data_dir: str | Path,
    *,
    timeout_seconds: float | None = None,
) -> Runnable:
    async def invoke(state: Any, config: RunnableConfig | None = None) -> Any:
        async def run_attempt(description: str) -> Any:
            return await agent.ainvoke(
                {"messages": [{"role": "user", "content": description}]},
                config=config,
            )

        return await run_reporter_with_recovery(
            invoke=run_attempt,
            initial_description=_first_user_message_text(state),
            data_dir=data_dir,
            timeout_seconds=timeout_seconds,
        )

    config = cast(RunnableConfig, getattr(agent, "config", {}))
    wrapped = RunnableLambda(invoke).with_config(config)
    object.__setattr__(wrapped, "reporter_recovery_enabled", True)
    return wrapped


class ReporterTaskRecoveryMiddleware(AgentMiddleware):
    def __init__(
        self,
        data_dir: str | Path,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        super().__init__()
        self._data_dir = Path(data_dir)
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def _is_reporter_task(request: ToolCallRequest) -> bool:
        args = request.tool_call.get("args")
        return (
            request.tool_call.get("name") == "task"
            and isinstance(args, dict)
            and args.get("subagent_type") == "reporter"
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if not self._is_reporter_task(request):
            return handler(request)
        args = request.tool_call["args"]
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

        async def invoke(description: str) -> ToolMessage | Command:
            patched_args = {**args, "description": description}
            tool_call = cast(ToolCall, {**request.tool_call, "args": patched_args})
            future = executor.submit(handler, request.override(tool_call=tool_call))
            return await asyncio.wrap_future(future)

        try:
            return asyncio.run(
                run_reporter_with_recovery(
                    invoke=invoke,
                    initial_description=str(args.get("description", "")),
                    data_dir=self._data_dir,
                    timeout_seconds=self._timeout_seconds,
                )
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if not self._is_reporter_task(request):
            return await handler(request)

        args = request.tool_call["args"]
        initial_description = str(args.get("description", ""))

        async def invoke(description: str) -> ToolMessage | Command:
            patched_args = {**args, "description": description}
            tool_call = cast(ToolCall, {**request.tool_call, "args": patched_args})
            return await handler(request.override(tool_call=tool_call))

        return await run_reporter_with_recovery(
            invoke=invoke,
            initial_description=initial_description,
            data_dir=self._data_dir,
            timeout_seconds=self._timeout_seconds,
        )
