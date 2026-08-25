from __future__ import annotations

import asyncio
import json
import os
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
    _required_reporter_refresh,
    _reporter_output_state,
    inspect_reporter_completion,
    reporter_attempt_timeout_seconds,
    run_reporter_with_recovery,
)


def _write_valid_synthesis(
    data_dir: Path,
    *,
    text: str = "# Synthesis\n\n## Executive Summary\n\nGrounded narrative.\n",
) -> None:
    (data_dir / "synthesis.md").write_text(text, encoding="utf-8")


def _write_valid_validation(data_dir: Path, *, status: str = "passed", errors: int = 0) -> None:
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


def _write_valid_targets(data_dir: Path) -> None:
    from src.agents.deep_interpreter.tools.report import _default_synthesis_targets

    (data_dir / "synthesis_targets.json").write_text(
        json.dumps(_default_synthesis_targets(str(data_dir))),
        encoding="utf-8",
    )


def _write_valid_html(data_dir: Path) -> None:
    (data_dir / "CCI_Analysis_Report.html").write_text(
        "<!DOCTYPE html><html><body>report</body></html>",
        encoding="utf-8",
    )


def _write_reporter_outputs(data_dir: Path, *, status: str, errors: int) -> None:
    _write_valid_synthesis(data_dir)
    _write_valid_validation(data_dir, status=status, errors=errors)
    _write_valid_targets(data_dir)
    _write_valid_html(data_dir)


def _write_reporter_downstream_outputs(
    data_dir: Path,
    *,
    status: str,
    errors: int,
) -> None:
    _write_valid_validation(data_dir, status=status, errors=errors)
    _write_valid_targets(data_dir)
    _write_valid_html(data_dir)


def _write_reporter_outputs_by_name(data_dir: Path, names: tuple[str, ...]) -> None:
    if "synthesis_validation.json" in names:
        _write_valid_validation(data_dir)
    if "synthesis_targets.json" in names:
        _write_valid_targets(data_dir)
    if "CCI_Analysis_Report.html" in names:
        _write_valid_html(data_dir)


def _write_refreshed_reporter_outputs_by_name(
    data_dir: Path,
    names: tuple[str, ...],
) -> None:
    if "synthesis_validation.json" in names:
        (data_dir / "synthesis_validation.json").write_text(
            json.dumps(
                {
                    "synthesis_guardrail": {
                        "status": "passed",
                        "final_error_count": 0,
                    },
                    "refreshed": True,
                }
            ),
            encoding="utf-8",
        )
    if "synthesis_targets.json" in names:
        from src.agents.deep_interpreter.tools.report import _default_synthesis_targets

        targets = _default_synthesis_targets(str(data_dir))
        targets["refreshed"] = True
        (data_dir / "synthesis_targets.json").write_text(
            json.dumps(targets),
            encoding="utf-8",
        )
    if "CCI_Analysis_Report.html" in names:
        (data_dir / "CCI_Analysis_Report.html").write_text(
            "<!DOCTYPE html><html><body>refreshed</body></html>",
            encoding="utf-8",
        )


async def _fake_reporter_finalizer(
    root: Path,
    required: tuple[str, ...],
) -> dict[str, Any]:
    _write_refreshed_reporter_outputs_by_name(root, required)
    return {
        "status": "passed",
        "guardrail": {"status": "passed", "final_error_count": 0},
        "required_refresh": list(required),
        "refreshed_outputs": list(required),
        "preserved_outputs": [],
    }


def _single_attempt_audit(data_dir: Path) -> dict[str, Any]:
    audit = json.loads((data_dir / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert audit["recovery_used"] is False
    assert audit["attempt_count"] == 1
    return audit


def test_required_reporter_refresh_only_requests_missing_html(
    tmp_path: Path,
) -> None:
    _write_valid_synthesis(tmp_path)
    _write_valid_validation(tmp_path)
    _write_valid_targets(tmp_path)
    hashes = _reporter_output_state(tmp_path)

    assert _required_reporter_refresh(tmp_path) == ("CCI_Analysis_Report.html",)
    assert _reporter_output_state(tmp_path) == hashes


@pytest.mark.parametrize(
    ("invalid_artifact", "expected"),
    [
        (None, ()),
        (
            "synthesis_validation.json",
            (
                "synthesis_validation.json",
                "synthesis_targets.json",
                "CCI_Analysis_Report.html",
            ),
        ),
        (
            "synthesis_targets.json",
            ("synthesis_targets.json", "CCI_Analysis_Report.html"),
        ),
        ("CCI_Analysis_Report.html", ("CCI_Analysis_Report.html",)),
    ],
)
def test_required_reporter_refresh_uses_downstream_suffix(
    tmp_path: Path,
    invalid_artifact: str | None,
    expected: tuple[str, ...],
) -> None:
    _write_reporter_outputs(tmp_path, status="passed", errors=0)
    _write_valid_targets(tmp_path)
    if invalid_artifact == "synthesis_validation.json":
        (tmp_path / invalid_artifact).write_text("{", encoding="utf-8")
    elif invalid_artifact == "synthesis_targets.json":
        (tmp_path / invalid_artifact).write_text("[]", encoding="utf-8")
    elif invalid_artifact == "CCI_Analysis_Report.html":
        (tmp_path / invalid_artifact).write_text("not html", encoding="utf-8")

    assert _required_reporter_refresh(tmp_path) == expected


def test_required_reporter_refresh_cascades_after_synthesis_change(
    tmp_path: Path,
) -> None:
    _write_reporter_outputs(tmp_path, status="passed", errors=0)
    _write_valid_targets(tmp_path)

    assert _required_reporter_refresh(tmp_path, synthesis_changed=True) == (
        "synthesis_validation.json",
        "synthesis_targets.json",
        "CCI_Analysis_Report.html",
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


def test_inspect_reporter_completion_treats_identical_rewrite_as_stale(
    tmp_path: Path,
) -> None:
    _write_reporter_outputs(tmp_path, status="passed", errors=0)
    previous = _reporter_output_state(tmp_path)

    for name in (
        "synthesis.md",
        "synthesis_validation.json",
        "synthesis_targets.json",
        "CCI_Analysis_Report.html",
    ):
        path = tmp_path / name
        original = path.read_bytes()
        path.write_bytes(original)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    result = inspect_reporter_completion(tmp_path, previous)

    assert result["complete"] is True
    assert result["stale_outputs"] == []

    refresh_result = inspect_reporter_completion(
        tmp_path,
        previous,
        required_refresh=("CCI_Analysis_Report.html",),
    )
    assert refresh_result["stale_outputs"] == ["CCI_Analysis_Report.html"]
    assert refresh_result["complete"] is False


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.agents.deep_interpreter.reporter_recovery._default_reporter_finalizer",
        _fake_reporter_finalizer,
    )
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
            _write_valid_targets(tmp_path)
            _write_valid_html(tmp_path)
        else:
            assert not (tmp_path / "synthesis.md").exists()
            for name in (
                "synthesis_validation.json",
                "synthesis_targets.json",
                "CCI_Analysis_Report.html",
            ):
                assert not (tmp_path / name).exists()
            assert "synthesis_not_markdown" in description
            assert "quarantined" in description.lower()
            assert "generate_html_report" not in description
            _write_reporter_outputs(tmp_path, status="passed", errors=0)
        return {
            "messages": [
                {"role": "assistant", "content": f"attempt-{len(prompts)}"}
            ]
        }

    result = await run_reporter_with_recovery(
        invoke=invoke,
        finalize=_fake_reporter_finalizer,
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
    assert audit["retry_preparation"]["action"] == "quarantined_invalid"
    assert audit["retry_preparation"]["failure_codes"] == [
        "papers_json_missing",
        "synthesis_not_markdown",
    ]


@pytest.mark.asyncio
async def test_reporter_recovery_retains_all_invalid_retry_error_codes(
    tmp_path: Path,
) -> None:
    prompts: list[str] = []
    expected_codes = ["papers_json_missing", "synthesis_not_markdown"]

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
            for code in expected_codes:
                assert code in description
            assert "generate_html_report" not in description
            _write_reporter_outputs(tmp_path, status="passed", errors=0)
        return {"messages": [{"role": "assistant", "content": "done"}]}

    await run_reporter_with_recovery(
        invoke=invoke,
        finalize=_fake_reporter_finalizer,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    audit = json.loads((tmp_path / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert audit["retry_preparation"]["failure_codes"] == expected_codes


@pytest.mark.asyncio
async def test_reporter_finalization_renders_missing_html_without_rewriting_valid_sidecars(
    tmp_path: Path,
) -> None:
    _write_valid_synthesis(tmp_path)
    _write_valid_validation(tmp_path)
    _write_valid_targets(tmp_path)
    before = _reporter_output_state(tmp_path)
    prompts: list[str] = []
    finalizer_calls: list[tuple[str, ...]] = []

    async def invoke(description: str) -> dict[str, str]:
        prompts.append(description)
        return {"content": "done"}

    async def finalize(root: Path, required: tuple[str, ...]) -> dict[str, Any]:
        finalizer_calls.append(required)
        (root / "CCI_Analysis_Report.html").write_text(
            "<!DOCTYPE html><html><body>ok</body></html>",
            encoding="utf-8",
        )
        return {
            "status": "passed",
            "guardrail": {"status": "passed", "final_error_count": 0},
            "required_refresh": list(required),
            "refreshed_outputs": list(required),
            "preserved_outputs": [
                "synthesis_validation.json",
                "synthesis_targets.json",
            ],
        }

    result = await run_reporter_with_recovery(
        invoke=invoke,
        finalize=finalize,
        initial_description="report",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert result == {"content": "done"}
    assert prompts == ["report"]
    assert finalizer_calls == [("CCI_Analysis_Report.html",)]
    after = _reporter_output_state(tmp_path)
    for name in ("synthesis.md", "synthesis_validation.json", "synthesis_targets.json"):
        assert after[name] == before[name]


@pytest.mark.asyncio
async def test_reporter_finalization_refreshes_all_sidecars_for_valid_synthesis_only(
    tmp_path: Path,
) -> None:
    _write_valid_synthesis(tmp_path)
    prompts: list[str] = []
    finalizer_calls: list[tuple[str, ...]] = []

    async def invoke(description: str) -> dict[str, str]:
        prompts.append(description)
        return {"content": "done"}

    async def finalize(root: Path, required: tuple[str, ...]) -> dict[str, Any]:
        finalizer_calls.append(required)
        _write_reporter_outputs_by_name(root, required)
        return {
            "status": "passed",
            "guardrail": {"status": "passed", "final_error_count": 0},
            "required_refresh": list(required),
            "refreshed_outputs": list(required),
            "preserved_outputs": [],
        }

    await run_reporter_with_recovery(
        invoke=invoke,
        finalize=finalize,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert prompts == ["normal reporter request"]
    assert finalizer_calls == [
        (
            "synthesis_validation.json",
            "synthesis_targets.json",
            "CCI_Analysis_Report.html",
        ),
    ]
    _single_attempt_audit(tmp_path)


@pytest.mark.asyncio
async def test_reporter_finalization_skips_when_all_artifacts_are_valid(
    tmp_path: Path,
) -> None:
    _write_reporter_outputs(tmp_path, status="passed", errors=0)
    prompts: list[str] = []
    finalizer_calls: list[tuple[str, ...]] = []

    async def invoke(description: str) -> dict[str, str]:
        prompts.append(description)
        return {"content": "done"}

    async def finalize(_root: Path, required: tuple[str, ...]) -> dict[str, Any]:
        finalizer_calls.append(required)
        return {}

    await run_reporter_with_recovery(
        invoke=invoke,
        finalize=finalize,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert prompts == ["normal reporter request"]
    assert finalizer_calls == []
    _single_attempt_audit(tmp_path)


@pytest.mark.asyncio
async def test_reporter_finalization_refreshes_from_invalid_validation(
    tmp_path: Path,
) -> None:
    _write_valid_synthesis(tmp_path)
    _write_valid_validation(tmp_path, status="failed", errors=1)
    prompts: list[str] = []
    finalizer_calls: list[tuple[str, ...]] = []

    async def invoke(description: str) -> dict[str, str]:
        prompts.append(description)
        return {"content": "done"}

    async def finalize(root: Path, required: tuple[str, ...]) -> dict[str, Any]:
        finalizer_calls.append(required)
        _write_reporter_outputs_by_name(root, required)
        return {
            "status": "passed",
            "guardrail": {"status": "passed", "final_error_count": 0},
            "required_refresh": list(required),
            "refreshed_outputs": list(required),
            "preserved_outputs": [],
        }

    await run_reporter_with_recovery(
        invoke=invoke,
        finalize=finalize,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert prompts == ["normal reporter request"]
    assert finalizer_calls == [
        (
            "synthesis_validation.json",
            "synthesis_targets.json",
            "CCI_Analysis_Report.html",
        ),
    ]
    _single_attempt_audit(tmp_path)


@pytest.mark.asyncio
async def test_reporter_finalization_refreshes_from_invalid_targets(
    tmp_path: Path,
) -> None:
    _write_valid_synthesis(tmp_path)
    _write_valid_validation(tmp_path)
    (tmp_path / "synthesis_targets.json").write_text("[]", encoding="utf-8")
    prompts: list[str] = []
    finalizer_calls: list[tuple[str, ...]] = []

    async def invoke(description: str) -> dict[str, str]:
        prompts.append(description)
        return {"content": "done"}

    async def finalize(root: Path, required: tuple[str, ...]) -> dict[str, Any]:
        finalizer_calls.append(required)
        _write_reporter_outputs_by_name(root, required)
        return {
            "status": "passed",
            "guardrail": {"status": "passed", "final_error_count": 0},
            "required_refresh": list(required),
            "refreshed_outputs": list(required),
            "preserved_outputs": [],
        }

    await run_reporter_with_recovery(
        invoke=invoke,
        finalize=finalize,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert prompts == ["normal reporter request"]
    assert finalizer_calls == [
        ("synthesis_targets.json", "CCI_Analysis_Report.html")
    ]
    _single_attempt_audit(tmp_path)


@pytest.mark.asyncio
async def test_reporter_finalization_refreshes_invalid_html(
    tmp_path: Path,
) -> None:
    _write_valid_synthesis(tmp_path)
    _write_valid_validation(tmp_path)
    _write_valid_targets(tmp_path)
    (tmp_path / "CCI_Analysis_Report.html").write_text("not html", encoding="utf-8")
    prompts: list[str] = []
    finalizer_calls: list[tuple[str, ...]] = []

    async def invoke(description: str) -> dict[str, str]:
        prompts.append(description)
        return {"content": "done"}

    async def finalize(root: Path, required: tuple[str, ...]) -> dict[str, Any]:
        finalizer_calls.append(required)
        _write_reporter_outputs_by_name(root, required)
        return {
            "status": "passed",
            "guardrail": {"status": "passed", "final_error_count": 0},
            "required_refresh": list(required),
            "refreshed_outputs": list(required),
            "preserved_outputs": [],
        }

    await run_reporter_with_recovery(
        invoke=invoke,
        finalize=finalize,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert prompts == ["normal reporter request"]
    assert finalizer_calls == [("CCI_Analysis_Report.html",)]
    _single_attempt_audit(tmp_path)


@pytest.mark.asyncio
async def test_reporter_recovery_retries_after_guardrail_repairs_are_exhausted(
    tmp_path: Path,
) -> None:
    prompts: list[str] = []

    async def invoke(description: str) -> dict[str, str]:
        prompts.append(description)
        assert not (tmp_path / "synthesis.md").exists() or len(prompts) == 1
        _write_valid_synthesis(
            tmp_path,
            text=f"# Synthesis {len(prompts)}\n\n## Summary\n\nText.\n",
        )
        return {"content": f"attempt-{len(prompts)}"}

    async def finalize(root: Path, required: tuple[str, ...]) -> dict[str, Any]:
        if len(prompts) == 1:
            (root / "synthesis_guardrail_final.json").write_text(
                json.dumps(
                    {
                        "issues": [
                            {
                                "severity": "error",
                                "code": "synthesis_consistency_mismatch",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return {
                "status": "guardrail_failed",
                "guardrail": {"status": "failed", "final_error_count": 1},
                "required_refresh": list(required),
            }
        _write_valid_validation(root)
        _write_valid_targets(root)
        _write_valid_html(root)
        return {
            "status": "passed",
            "guardrail": {"status": "passed", "final_error_count": 0},
            "required_refresh": list(required),
        }

    result = await run_reporter_with_recovery(
        invoke=invoke,
        finalize=finalize,
        initial_description="report",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert result == {"content": "attempt-2"}
    audit = json.loads((tmp_path / "reporter_recovery.json").read_text())
    assert audit["retry_preparation"]["action"] == "quarantined_guardrail_failed"
    assert audit["retry_preparation"]["failure_codes"] == [
        "synthesis_consistency_mismatch"
    ]


@pytest.mark.asyncio
async def test_reporter_finalization_guardrail_failure_uses_clean_retry_path(
    tmp_path: Path,
) -> None:
    _write_valid_synthesis(tmp_path)
    prompts: list[str] = []
    finalizer_calls: list[tuple[str, ...]] = []

    async def invoke(description: str) -> dict[str, str]:
        prompts.append(description)
        if len(prompts) == 2:
            assert not (tmp_path / "synthesis.md").exists()
            assert "generate_html_report" not in description
            _write_valid_synthesis(tmp_path, text="# Synthesis 2\n\n## Summary\n\nText.\n")
        return {"content": f"attempt-{len(prompts)}"}

    async def finalize(root: Path, required: tuple[str, ...]) -> dict[str, Any]:
        finalizer_calls.append(required)
        if len(prompts) == 2:
            _write_reporter_downstream_outputs(root, status="passed", errors=0)
            return {
                "status": "passed",
                "guardrail": {"status": "passed", "final_error_count": 0},
                "required_refresh": list(required),
                "refreshed_outputs": list(required),
                "preserved_outputs": [],
            }
        (root / "synthesis_guardrail_final.json").write_text(
            json.dumps(
                {
                    "issues": [
                        {
                            "severity": "error",
                            "code": "synthesis_consistency_mismatch",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return {
            "status": "guardrail_failed",
            "guardrail": {"status": "failed", "final_error_count": 1},
            "required_refresh": list(required),
            "refreshed_outputs": [],
            "preserved_outputs": ["synthesis.md"],
        }

    result = await run_reporter_with_recovery(
        invoke=invoke,
        finalize=finalize,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert result == {"content": "attempt-2"}
    assert prompts[0] == "normal reporter request"
    assert prompts[1].startswith("[REPORTER_RECOVERY]")
    assert finalizer_calls == [
        (
            "synthesis_validation.json",
            "synthesis_targets.json",
            "CCI_Analysis_Report.html",
        ),
        (
            "synthesis_validation.json",
            "synthesis_targets.json",
            "CCI_Analysis_Report.html",
        ),
    ]
    audit = json.loads((tmp_path / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert audit["status"] == "passed"
    assert audit["attempt_count"] == 2
    assert audit["recovery_used"] is True
    assert audit["retry_preparation"]["action"] == "quarantined_guardrail_failed"
    assert audit["retry_preparation"]["failure_codes"] == [
        "synthesis_consistency_mismatch"
    ]


@pytest.mark.asyncio
async def test_reporter_recovery_retries_when_synthesis_is_absent(
    tmp_path: Path,
) -> None:
    prompts: list[str] = []

    async def invoke(description: str) -> dict[str, str]:
        prompts.append(description)
        if len(prompts) == 2:
            assert "generate_html_report" not in description
            _write_valid_synthesis(tmp_path)
        return {"content": f"attempt-{len(prompts)}"}

    async def finalize(root: Path, required: tuple[str, ...]) -> dict[str, Any]:
        _write_reporter_outputs_by_name(root, required)
        return {
            "status": "passed",
            "guardrail": {"status": "passed", "final_error_count": 0},
            "required_refresh": list(required),
            "refreshed_outputs": list(required),
            "preserved_outputs": [],
        }

    result = await run_reporter_with_recovery(
        invoke=invoke,
        finalize=finalize,
        initial_description="report",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert result == {"content": "attempt-2"}
    assert len(prompts) == 2
    audit = json.loads((tmp_path / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert audit["status"] == "passed"
    assert audit["retry_preparation"]["action"] == "absent"


@pytest.mark.asyncio
async def test_reporter_finalization_exception_records_failed_attempt_audit(
    tmp_path: Path,
) -> None:
    _write_valid_synthesis(tmp_path)

    async def invoke(_description: str) -> dict[str, str]:
        return {"content": "done"}

    async def finalize(_root: Path, _required: tuple[str, ...]) -> dict[str, Any]:
        raise RuntimeError("renderer exploded")

    with pytest.raises(ReporterRecoveryError) as exc_info:
        await run_reporter_with_recovery(
            invoke=invoke,
            finalize=finalize,
            initial_description="normal reporter request",
            data_dir=tmp_path,
            timeout_seconds=1,
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "renderer exploded"
    audit = json.loads((tmp_path / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert audit["status"] == "failed"
    assert audit["attempt_count"] == 1
    assert audit["recovery_used"] is False
    assert audit["attempts"][0]["finalizer"] == {
        "status": "exception",
        "exception_type": "RuntimeError",
        "exception_repr": "RuntimeError('renderer exploded')",
    }


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
        finalize=_fake_reporter_finalizer,
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
async def test_reporter_recovery_accepts_preserved_valid_outputs_when_no_refresh_required(
    tmp_path: Path,
) -> None:
    _write_reporter_outputs(tmp_path, status="passed", errors=0)
    prompts: list[str] = []

    async def invoke(description: str) -> dict[str, list[dict[str, str]]]:
        prompts.append(description)
        return {"messages": [{"role": "assistant", "content": "done"}]}

    await run_reporter_with_recovery(
        invoke=invoke,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert len(prompts) == 1


def test_reporter_task_recovery_middleware_waits_for_timed_out_sync_reporter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.agents.deep_interpreter.reporter_recovery._default_reporter_finalizer",
        _fake_reporter_finalizer,
    )
    middleware = ReporterTaskRecoveryMiddleware(data_dir=tmp_path, timeout_seconds=0.05)
    attempts = 0
    events: list[str] = []
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
            events.append("attempt-1-start")
            time.sleep(0.2)
            (tmp_path / "synthesis.md").write_text(
                "<p>late invalid synthesis</p>",
                encoding="utf-8",
            )
            events.append("attempt-1-finish")
        else:
            events.append("attempt-2-start")
            _write_reporter_outputs(tmp_path, status="passed", errors=0)
            events.append("attempt-2-finish")
        return ToolMessage(content="done", tool_call_id="call-reporter")

    started = time.monotonic()
    result = middleware.wrap_tool_call(request, handler)
    duration = time.monotonic() - started

    assert isinstance(result, ToolMessage)
    assert attempts == 2
    assert events == [
        "attempt-1-start",
        "attempt-1-finish",
        "attempt-2-start",
        "attempt-2-finish",
    ]
    assert duration >= 0.2
    time.sleep(0.1)
    assert (tmp_path / "synthesis.md").read_text(encoding="utf-8").startswith(
        "# Synthesis"
    )


@pytest.mark.asyncio
async def test_reporter_recovery_persists_retry_audit_when_second_attempt_raises(
    tmp_path: Path,
) -> None:
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
            return {"messages": [{"role": "assistant", "content": "attempt-1"}]}

        assert not (tmp_path / "synthesis.md").exists()
        raise RuntimeError("retry exploded")

    with pytest.raises(RuntimeError, match="retry exploded"):
        await run_reporter_with_recovery(
            invoke=invoke,
            initial_description="normal reporter request",
            data_dir=tmp_path,
            timeout_seconds=1,
        )

    audit = json.loads((tmp_path / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert prompts[1].startswith("[REPORTER_RECOVERY]")
    assert audit["status"] == "failed"
    assert audit["attempt_count"] == 2
    assert audit["recovery_used"] is True
    assert audit["retry_preparation"]["action"] == "quarantined_invalid"
    assert "synthesis_not_markdown" in audit["retry_preparation"]["failure_codes"]
    assert audit["attempts"][0]["completion"]["guardrail_status"] == "failed"
    assert audit["attempts"][1]["exception_type"] == "RuntimeError"
    assert audit["attempts"][1]["exception_repr"] == "RuntimeError('retry exploded')"
    assert audit["attempts"][1]["completion"]["missing_outputs"] == [
        "synthesis.md",
        "synthesis_validation.json",
        "synthesis_targets.json",
        "CCI_Analysis_Report.html",
    ]


@pytest.mark.asyncio
async def test_reporter_recovery_records_byte_identical_invalid_retry(
    tmp_path: Path,
) -> None:
    invalid = "<p>Unsupported fragment</p>"

    async def invoke(_description: str) -> dict[str, list[dict[str, str]]]:
        (tmp_path / "synthesis.md").write_text(invalid, encoding="utf-8")
        return {"messages": [{"role": "assistant", "content": "done"}]}

    with pytest.raises(ReporterRecoveryError):
        await run_reporter_with_recovery(
            invoke=invoke,
            initial_description="normal reporter request",
            data_dir=tmp_path,
            timeout_seconds=1,
        )

    audit = json.loads((tmp_path / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert audit["attempts"][1]["repeated_invalid_synthesis"] is True
    assert (tmp_path / "synthesis_reporter_attempt1.md").read_text(
        encoding="utf-8"
    ) == invalid


@pytest.mark.asyncio
async def test_reporter_recovery_raises_after_second_invalid_attempt(
    tmp_path: Path,
) -> None:
    prompts: list[str] = []

    async def invoke(description: str) -> dict[str, list[dict[str, str]]]:
        prompts.append(description)
        (tmp_path / "synthesis.md").write_text(
            "<p>Unsupported fragment</p>",
            encoding="utf-8",
        )
        _write_valid_validation(tmp_path, status="failed", errors=1)
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
