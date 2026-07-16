"""Tests for write_file argument guard middleware."""

import json
from typing import Any

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from src.agents.deep_interpreter.middleware import WriteFileArgGuardMiddleware
from src.agents.deep_interpreter.subagents.configs import get_subagents


def _request(tool_name: str, args: dict[str, Any]) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"id": "tc_1", "name": tool_name, "args": args},
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )


def test_write_file_content_dict_is_coerced_to_json_string():
    middleware = WriteFileArgGuardMiddleware()
    req = _request("write_file", {"file_path": "/foo.json", "content": {"a": 1, "b": ["x"]}})

    patched = middleware._patched_request(req)
    content = patched.tool_call["args"]["content"]

    assert isinstance(content, str)
    assert json.loads(content) == {"a": 1, "b": ["x"]}


def test_write_file_content_none_is_coerced_to_empty_string():
    middleware = WriteFileArgGuardMiddleware()
    req = _request("write_file", {"file_path": "/foo.txt", "content": None})

    patched = middleware._patched_request(req)
    assert patched.tool_call["args"]["content"] == ""


def test_non_write_file_tool_call_is_unchanged():
    middleware = WriteFileArgGuardMiddleware()
    req = _request("search_literature_dynamic", {"query": "TGFB"})

    patched = middleware._patched_request(req)
    assert patched is req


@pytest.mark.parametrize(
    "file_path",
    [
        "/hypothesis_report.json",
        "/hypothesis_report2.json",
        "/hypothesis_reportv2.json",
        "/hypothesis_report_draft.json",
        "/hypothesis_report.tmp.json",
        "/hypothesis_report-draft.json",
        "evidence\\hypothesis_report_draft.json",
        "C:\\tmp\\Hypothesis_Report_Draft.json",
    ],
)
def test_write_file_blocks_hypothesis_report_artifacts(file_path):
    middleware = WriteFileArgGuardMiddleware()
    req = _request(
        "write_file",
        {
            "file_path": file_path,
            "content": {"hypotheses": []},
        },
    )
    called = False

    def handler(_request):
        nonlocal called
        called = True
        raise AssertionError("handler should not be called for blocked artifacts")

    result = middleware.wrap_tool_call(req, handler)

    assert called is False
    assert isinstance(result, ToolMessage)
    assert "write_file" in str(result.content)
    assert "save_hypothesis_report" in str(result.content)


def test_write_file_blocks_hypothesis_report_when_file_path_conflicts_with_path():
    middleware = WriteFileArgGuardMiddleware()
    req = _request(
        "write_file",
        {
            "path": "/ok.txt",
            "file_path": "/hypothesis_report_draft.json",
            "content": "{}",
        },
    )
    called = False

    def handler(_request):
        nonlocal called
        called = True
        raise AssertionError("handler should not be called for blocked artifacts")

    result = middleware.wrap_tool_call(req, handler)

    assert called is False
    assert isinstance(result, ToolMessage)
    assert "save_hypothesis_report" in str(result.content)


@pytest.mark.parametrize("tool_name", ["write_file", "edit_file"])
@pytest.mark.parametrize(
    "file_path",
    ["drug.md", "target_assessment.json", "hypothesis_report_draft.json", "report_data.json"],
)
def test_mutation_tools_block_all_managed_report_artifacts(tool_name, file_path):
    middleware = WriteFileArgGuardMiddleware()
    request = _request(tool_name, {"file_path": file_path, "content": "x"})
    called = False

    def handler(_request):
        nonlocal called
        called = True
        return ToolMessage(content="unexpected", tool_call_id="tc_1")

    result = middleware.wrap_tool_call(request, handler)
    assert called is False
    assert "report_data.json" in str(result.content)


def test_write_file_allows_hypothesis_report_near_miss():
    middleware = WriteFileArgGuardMiddleware()
    req = _request(
        "write_file",
        {
            "file_path": "/my_hypothesis_report_draft.json",
            "content": "{}",
        },
    )
    called = False

    def handler(_request):
        nonlocal called
        called = True
        return ToolMessage(content="ok", tool_call_id="tc_1")

    result = middleware.wrap_tool_call(req, handler)

    assert called is True
    assert isinstance(result, ToolMessage)
    assert result.content == "ok"


def test_subagents_include_write_file_guard_middleware():
    subagents = get_subagents()

    for subagent in subagents:
        middleware = subagent.get("middleware", [])
        assert middleware, f"{subagent['name']} missing middleware list"
        assert isinstance(middleware[0], WriteFileArgGuardMiddleware)
