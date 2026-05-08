"""T5 RED: AnnotationDensityMiddleware rejects sparse-annotation save_drug_md.

The summarizer's report_writer must annotate prose sentences inside
``<!-- EXPAND -->`` regions with ``[source: <field>]`` markers so the
``UNANCHORED_SENTENCE`` validator can verify per-sentence provenance. Prompt-
only enforcement was unreliable on local LLMs (1/20 in the qwen3.5:35b run).

This middleware intercepts ``save_drug_md`` (``wrap_tool_call``); on the first
invocation it counts ``[source:<field>]`` annotations in the saved content.
If the count is below ``threshold`` AND there is at least one EXPAND-region
sentence, it returns a structured rejection ToolMessage directing the writer
to add annotations. Otherwise the call passes through to the underlying tool.

Tests:
1. Sparse annotations + EXPAND prose -> rejection ToolMessage, underlying tool
   NOT invoked.
2. Dense annotations -> pass-through, underlying tool invoked once.
3. No EXPAND regions at all -> pass-through (don't gate non-EXPAND saves).
4. Non-target tool name -> pass-through unchanged.
5. async awrap_tool_call honors the same gate.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    tool_name: str, args: dict[str, Any], tool_id: str = "call_save_001"
) -> Any:
    class _FakeRequest:
        tool_call = {"name": tool_name, "id": tool_id, "args": args}

    return _FakeRequest()


_DENSE_CONTENT = "\n\n".join(
    [
        "# Report",
        "<!-- EXPAND:s1 -->",
        ". ".join(
            f"Sentence {i} explaining the finding [source: stage3_TGFB1.json]"
            for i in range(12)
        )
        + ".",
        "<!-- /EXPAND -->",
    ]
)

_SPARSE_CONTENT = "\n\n".join(
    [
        "# Report",
        "<!-- EXPAND:s1 -->",
        ". ".join(f"Sentence {i} stating a fact" for i in range(20))
        + ". And one annotated [source: stage3_TGFB1.json].",
        "<!-- /EXPAND -->",
    ]
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sparse_annotations_in_expand_region_returns_blocked_tool_message() -> None:
    from src.agents.drug_target.subagents.summarizer.middleware import (
        AnnotationDensityMiddleware,
    )

    middleware = AnnotationDensityMiddleware(threshold=10)
    handler = MagicMock(
        return_value=ToolMessage(content="saved", tool_call_id="call_save_001")
    )
    req = _make_request("save_drug_md", {"content": _SPARSE_CONTENT})

    result = middleware.wrap_tool_call(req, handler)

    handler.assert_not_called()
    assert isinstance(result, ToolMessage)
    payload = json.loads(result.content)
    assert payload.get("ok") is False
    assert "Annotation density" in payload.get("error", "")
    assert result.tool_call_id == "call_save_001"


def test_dense_annotations_passes_through() -> None:
    from src.agents.drug_target.subagents.summarizer.middleware import (
        AnnotationDensityMiddleware,
    )

    middleware = AnnotationDensityMiddleware(threshold=10)
    handler = MagicMock(
        return_value=ToolMessage(content="saved", tool_call_id="call_save_002")
    )
    req = _make_request("save_drug_md", {"content": _DENSE_CONTENT}, "call_save_002")

    result = middleware.wrap_tool_call(req, handler)

    handler.assert_called_once_with(req)
    assert isinstance(result, ToolMessage)
    assert result.content == "saved"


def test_no_expand_region_passes_through_even_when_sparse() -> None:
    """When the report has no EXPAND regions, annotation density is moot."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        AnnotationDensityMiddleware,
    )

    middleware = AnnotationDensityMiddleware(threshold=10)
    handler = MagicMock(
        return_value=ToolMessage(content="saved", tool_call_id="call_save_003")
    )
    content = "# Report\n\nA short note with no EXPAND comments."
    req = _make_request("save_drug_md", {"content": content}, "call_save_003")

    result = middleware.wrap_tool_call(req, handler)

    handler.assert_called_once_with(req)
    assert result.content == "saved"


def test_non_target_tool_passes_through() -> None:
    from src.agents.drug_target.subagents.summarizer.middleware import (
        AnnotationDensityMiddleware,
    )

    middleware = AnnotationDensityMiddleware(threshold=10)
    handler = MagicMock(
        return_value=ToolMessage(content="ok", tool_call_id="call_other_001")
    )
    req = _make_request("validate_drug_md", {"path": "drug.md"}, "call_other_001")

    result = middleware.wrap_tool_call(req, handler)

    handler.assert_called_once_with(req)
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_awrap_tool_call_blocks_sparse_save() -> None:
    from src.agents.drug_target.subagents.summarizer.middleware import (
        AnnotationDensityMiddleware,
    )

    middleware = AnnotationDensityMiddleware(threshold=10)

    async def _async_handler(_req: Any) -> ToolMessage:
        return ToolMessage(content="saved", tool_call_id="call_save_async")

    req = _make_request(
        "save_drug_md", {"content": _SPARSE_CONTENT}, "call_save_async"
    )
    result = await middleware.awrap_tool_call(req, _async_handler)

    assert isinstance(result, ToolMessage)
    payload = json.loads(result.content)
    assert payload.get("ok") is False


def test_register_in_create_summarizer_agent_middleware_list() -> None:
    """Normal deterministic summarizer must not wire legacy save_drug_md middleware."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        AnnotationDensityMiddleware,
    )

    # Patch create_deep_agent to capture the middleware list passed in.
    from unittest.mock import patch

    captured: dict[str, Any] = {}

    class _StubAgent:
        def with_config(self, *_args: Any, **_kwargs: Any) -> "_StubAgent":
            return self

    def _fake_create_deep_agent(**kwargs: Any) -> _StubAgent:
        captured["middleware"] = kwargs.get("middleware", [])
        return _StubAgent()

    with patch(
        "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
        side_effect=_fake_create_deep_agent,
    ):
        from src.agents.drug_target.subagents.summarizer.agent import (
            create_summarizer_agent,
        )

        create_summarizer_agent()

    types_in_stack = [type(m).__name__ for m in captured["middleware"]]
    assert "AnnotationDensityMiddleware" not in types_in_stack, (
        f"AnnotationDensityMiddleware is legacy-only and must not be registered; got {types_in_stack}"
    )
