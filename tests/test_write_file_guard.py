"""Tests for write_file argument guard middleware."""

import json

from langgraph.prebuilt.tool_node import ToolCallRequest

from src.agents.deep_interpreter.middleware import WriteFileArgGuardMiddleware
from src.agents.deep_interpreter.subagents.configs import get_subagents


def _request(tool_name: str, args: object) -> ToolCallRequest:
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


def test_subagents_include_write_file_guard_middleware():
    subagents = get_subagents()

    for subagent in subagents:
        middleware = subagent.get("middleware", [])
        assert middleware, f"{subagent['name']} missing middleware list"
        assert isinstance(middleware[0], WriteFileArgGuardMiddleware)

