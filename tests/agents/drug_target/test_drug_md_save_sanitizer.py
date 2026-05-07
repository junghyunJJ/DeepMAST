"""RED tests — DrugMdSaveSanitizerMiddleware.

10 scenarios covering the three deterministic sanitizations:
  1. UNEXPANDED_PLACEHOLDER: strip <!-- EXPAND: ... --> markers
  2. EMPTY_GAP_ANALYSIS: fill empty Gap Analysis section with default body
  3. UNCITED_QUANTITATIVE: append [source: census evidence] to uncited stat lines

Each test builds a minimal _FakeRequest (same pattern as
test_summarizer_finalization_gate.py), calls wrap_tool_call, and inspects
the args that were forwarded to the handler.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage


# ---------------------------------------------------------------------------
# Helpers — minimal ToolCallRequest stub (mirrors finalization gate tests)
# ---------------------------------------------------------------------------


def _make_request(tool_name: str, args: dict | None = None, tool_id: str = "call_001") -> Any:
    """Return a minimal ToolCallRequest-like object with .tool_call dict."""

    class _FakeRequest:
        tool_call = {"name": tool_name, "id": tool_id, "args": args or {}}

    return _FakeRequest()


def _make_save_request(content: str, tool_id: str = "call_save_001") -> Any:
    return _make_request("save_drug_md", {"content": content, "data_dir": "/tmp/test"}, tool_id)


def _make_handler(tool_id: str = "call_save_001") -> MagicMock:
    return MagicMock(
        spec=["__call__"],
        return_value=ToolMessage(content=json.dumps({"saved": True}), tool_call_id=tool_id),
    )


def _get_middleware():
    from src.agents.drug_target.subagents.summarizer.middleware import (
        DrugMdSaveSanitizerMiddleware,
    )
    return DrugMdSaveSanitizerMiddleware


def _sanitized_content(handler: MagicMock) -> str:
    """Extract the content arg that was forwarded to the handler after sanitization."""
    assert handler.called, "Handler was not called — middleware may have blocked it"
    call_args = handler.call_args
    # The handler receives the (possibly patched) request as the first positional arg
    forwarded_request = call_args[0][0]
    return forwarded_request.tool_call["args"]["content"]


# ---------------------------------------------------------------------------
# 1. Strip single-line EXPAND marker
# ---------------------------------------------------------------------------


def test_strips_expand_markers_single_line() -> None:
    """Single <!-- EXPAND: ... --> marker on a line is removed; surrounding text preserved."""
    Cls = _get_middleware()
    mw = Cls()
    content = "Hello <!-- EXPAND: some description --> world"
    req = _make_save_request(content)
    handler = _make_handler()

    mw.wrap_tool_call(req, handler)

    result = _sanitized_content(handler)
    assert "<!-- EXPAND:" not in result, f"EXPAND marker should be stripped; got: {result!r}"
    assert "Hello" in result
    assert "world" in result


# ---------------------------------------------------------------------------
# 2. Strip multiple EXPAND markers across lines
# ---------------------------------------------------------------------------


def test_strips_expand_markers_multi_line() -> None:
    """Multiple <!-- EXPAND: ... --> markers across lines are all stripped."""
    Cls = _get_middleware()
    mw = Cls()
    content = (
        "## Section A\n"
        "<!-- EXPAND: describe mechanism -->\n"
        "Some text here.\n"
        "<!-- EXPAND: add clinical data -->\n"
        "More text.\n"
    )
    req = _make_save_request(content)
    handler = _make_handler()

    mw.wrap_tool_call(req, handler)

    result = _sanitized_content(handler)
    assert "<!-- EXPAND:" not in result
    assert "## Section A" in result
    assert "Some text here." in result
    assert "More text." in result


# ---------------------------------------------------------------------------
# 3. Strip EXPAND marker spanning multiple lines (newlines inside comment)
# ---------------------------------------------------------------------------


def test_strips_expand_markers_with_newlines_inside() -> None:
    """Multi-line <!-- EXPAND:\\n  ...\\n--> block is stripped in full."""
    Cls = _get_middleware()
    mw = Cls()
    content = (
        "Before marker.\n"
        "<!-- EXPAND:\n"
        "  multi-line\n"
        "  description\n"
        "-->\n"
        "After marker.\n"
    )
    req = _make_save_request(content)
    handler = _make_handler()

    mw.wrap_tool_call(req, handler)

    result = _sanitized_content(handler)
    assert "<!-- EXPAND:" not in result
    assert "Before marker." in result
    assert "After marker." in result


# ---------------------------------------------------------------------------
# 4. Preserve non-EXPAND HTML comments
# ---------------------------------------------------------------------------


def test_preserves_other_html_comments() -> None:
    """Non-EXPAND HTML comments are NOT stripped (only EXPAND-prefixed ones)."""
    Cls = _get_middleware()
    mw = Cls()
    content = (
        "<!-- TODO: implement -->\n"
        "<!-- generated -->\n"
        "Normal content.\n"
        "<!-- EXPAND: this one goes --> but this stays.\n"
    )
    req = _make_save_request(content)
    handler = _make_handler()

    mw.wrap_tool_call(req, handler)

    result = _sanitized_content(handler)
    assert "<!-- TODO: implement -->" in result, "Non-EXPAND comment should be preserved"
    assert "<!-- generated -->" in result, "Non-EXPAND comment should be preserved"
    assert "<!-- EXPAND:" not in result, "EXPAND comment should be stripped"


# ---------------------------------------------------------------------------
# 5. Fill empty Gap Analysis section with default body
# ---------------------------------------------------------------------------


def test_fills_empty_gap_analysis_with_default_body() -> None:
    """Empty ### Gap Analysis section body is filled with a default placeholder."""
    Cls = _get_middleware()
    mw = Cls()
    content = (
        "## Introduction\n"
        "Some intro text.\n\n"
        "### Gap Analysis\n"
        "\n"
        "\n"
        "## Next Section\n"
        "Next content.\n"
    )
    req = _make_save_request(content)
    handler = _make_handler()

    mw.wrap_tool_call(req, handler)

    result = _sanitized_content(handler)
    assert "### Gap Analysis" in result
    # The default body must contain these words per the design spec
    assert "data limitations" in result.lower() or "Data limitations" in result, (
        f"Default Gap Analysis body should mention data limitations; got:\n{result}"
    )
    assert "missing evidence" in result.lower() or "Missing evidence" in result, (
        f"Default Gap Analysis body should mention missing evidence; got:\n{result}"
    )
    assert "open questions" in result.lower() or "Open questions" in result, (
        f"Default Gap Analysis body should mention open questions; got:\n{result}"
    )
    # Next section must still follow
    assert "## Next Section" in result


# ---------------------------------------------------------------------------
# 6. Preserve non-empty Gap Analysis section
# ---------------------------------------------------------------------------


def test_preserves_non_empty_gap_analysis() -> None:
    """When Gap Analysis already has content, it must not be replaced."""
    Cls = _get_middleware()
    mw = Cls()
    existing_body = "The study has limited GWAS coverage for HLA genes."
    content = (
        "### Gap Analysis\n"
        f"{existing_body}\n\n"
        "## Next\n"
    )
    req = _make_save_request(content)
    handler = _make_handler()

    mw.wrap_tool_call(req, handler)

    result = _sanitized_content(handler)
    assert existing_body in result, (
        f"Non-empty Gap Analysis body should be preserved; result:\n{result}"
    )


# ---------------------------------------------------------------------------
# 7. Append source citation to uncited census stat line
# ---------------------------------------------------------------------------


def test_appends_source_citation_to_uncited_census_stats() -> None:
    """Stat line without [source:] tag gets [source: census evidence] appended."""
    Cls = _get_middleware()
    mw = Cls()
    content = "- Census: risk_ratio=17.863, p_value=0.0\n"
    req = _make_save_request(content)
    handler = _make_handler()

    mw.wrap_tool_call(req, handler)

    result = _sanitized_content(handler)
    assert "[source:" in result, (
        f"Uncited stat line should have [source: ...] appended; got: {result!r}"
    )
    # Original content still present
    assert "risk_ratio=17.863" in result


# ---------------------------------------------------------------------------
# 8. Preserve already-cited stat lines
# ---------------------------------------------------------------------------


def test_preserves_already_cited_stats() -> None:
    """Stat lines that already have [source: ...] on the same line must not be modified."""
    Cls = _get_middleware()
    mw = Cls()
    original_line = "- Census: risk_ratio=4.50, p_value=0.0 [source: census_x_y.csv]"
    content = original_line + "\n"
    req = _make_save_request(content)
    handler = _make_handler()

    mw.wrap_tool_call(req, handler)

    result = _sanitized_content(handler)
    # Original line should appear verbatim (no double-citation)
    assert result.strip() == original_line, (
        f"Already-cited line must not be modified; got: {result!r}"
    )


# ---------------------------------------------------------------------------
# 9. Non-save_drug_md tool passes through unchanged
# ---------------------------------------------------------------------------


def test_non_save_drug_md_tool_passes_through() -> None:
    """When tool_name != 'save_drug_md', request passes through without modification."""
    Cls = _get_middleware()
    mw = Cls()
    original_content = "Some content with <!-- EXPAND: keep me --> untouched."
    req = _make_request(
        "validate_drug_md",
        {"content": original_content},
        "call_validate_001",
    )
    handler = _make_handler("call_validate_001")

    mw.wrap_tool_call(req, handler)

    handler.assert_called_once()
    forwarded = handler.call_args[0][0]
    assert forwarded is req, "Non-save_drug_md request must be forwarded unchanged"
    assert forwarded.tool_call["args"]["content"] == original_content


# ---------------------------------------------------------------------------
# 10. save_drug_md without 'content' arg passes through unchanged
# ---------------------------------------------------------------------------


def test_save_drug_md_without_content_arg_passes_through() -> None:
    """save_drug_md with args lacking 'content' key passes through without error."""
    Cls = _get_middleware()
    mw = Cls()
    req = _make_request("save_drug_md", {"data_dir": "/some/path"}, "call_no_content_001")
    handler = _make_handler("call_no_content_001")

    mw.wrap_tool_call(req, handler)

    handler.assert_called_once()
    forwarded = handler.call_args[0][0]
    assert forwarded is req, "Request without content must be forwarded unchanged"
    assert "content" not in forwarded.tool_call["args"]
