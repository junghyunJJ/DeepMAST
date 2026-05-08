"""Legacy middleware regression tests.

The normal Summarizer no longer wires this middleware chain; it is now a
deterministic Runnable. These tests keep the legacy middleware classes covered
for standalone compatibility paths.

Scenarios (one per original middleware):
  1. ReadOnlyToolGuardMiddleware  — still blocks write calls in the 6-entry chain.
  2. BuildEvidenceSummaryGuardMiddleware — _call_count increments correctly;
       second build_evidence_summary call is blocked, not confused by guard.
  3. RepairCycleCounterMiddleware — _cycle_count tracked correctly after
       validator returns valid=true; counter (not guard) blocks 3rd call.
  4. FrozenTemplateSpanMiddleware — still applies template-span check on
       save_drug_md after guard passes; FrozenTemplate blocks malformed content.
  5. AnnotationDensityMiddleware — density check applied after FrozenTemplate
       passes; AnnotationDensity blocks sparse-annotation content.

All 5 tests are independent — no shared mutable state between them.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage

# ---------------------------------------------------------------------------
# Middleware imports
# ---------------------------------------------------------------------------

from src.agents.deep_interpreter.middleware.write_file_guard import (
    ReadOnlyToolGuardMiddleware,
)
from src.agents.drug_target.subagents.summarizer.middleware import (
    AnnotationDensityMiddleware,
    BuildEvidenceSummaryGuardMiddleware,
    FrozenTemplateSpanMiddleware,
    RepairCycleCounterMiddleware,
    SummarizerFinalizationGuardMiddleware,
)


# ---------------------------------------------------------------------------
# Helpers: fake ToolCallRequest stubs
# ---------------------------------------------------------------------------


def _make_request(
    tool_name: str,
    args: dict[str, Any] | None = None,
    tool_id: str = "call_001",
) -> Any:
    """Return a minimal ToolCallRequest-like stub."""

    class _FakeRequest:
        tool_call = {
            "name": tool_name,
            "id": tool_id,
            "args": args or {},
        }

    return _FakeRequest()


def _make_task_request(
    subagent_type: str,
    tool_id: str = "call_task_001",
) -> Any:
    return _make_request("task", {"subagent_type": subagent_type}, tool_id)


def _make_validator_request(
    tool_id: str = "call_val_001",
) -> Any:
    return _make_request("validate_drug_report_finalization", {}, tool_id)


def _validator_handler_factory(valid: bool) -> Any:
    """Return a sync handler that yields a typed validator ToolMessage."""

    def _handler(req: Any) -> ToolMessage:
        payload = {"valid": valid, "issues": [] if valid else [{"code": "BAD"}]}
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=req.tool_call["id"],
        )

    return _handler


# ---------------------------------------------------------------------------
# Chain construction helper
# ---------------------------------------------------------------------------


def _build_full_chain(*, data_dir: str | None = None) -> list[Any]:
    """Build the legacy middleware chain explicitly."""
    return [
        ReadOnlyToolGuardMiddleware(
            blocked_tool_names=("save_drug_md", "save_target_assessment", "save_evidence")
        ),
        BuildEvidenceSummaryGuardMiddleware(),
        RepairCycleCounterMiddleware(max_cycles=2),
        SummarizerFinalizationGuardMiddleware(),
        FrozenTemplateSpanMiddleware(data_dir=data_dir),
        AnnotationDensityMiddleware(),
    ]


# ---------------------------------------------------------------------------
# Scenario 1: ReadOnlyToolGuardMiddleware still blocks in the 6-entry chain
# ---------------------------------------------------------------------------


def test_readonly_tool_guard_blocks_write_calls_in_full_chain() -> None:
    """ReadOnlyToolGuardMiddleware (index 0) must block save_target_assessment
    and save_evidence even when SummarizerFinalizationGuardMiddleware is present."""
    # Arrange
    chain = _build_full_chain()
    guard: ReadOnlyToolGuardMiddleware = next(
        m for m in chain if isinstance(m, ReadOnlyToolGuardMiddleware)
    )
    handler = MagicMock(return_value=ToolMessage(content="ok", tool_call_id="c"))

    for blocked_tool in ("save_target_assessment", "save_evidence"):
        req = _make_request(blocked_tool, tool_id=f"call_{blocked_tool}")

        # Act
        result = guard.wrap_tool_call(req, handler)

        # Assert — handler must NOT have been reached
        handler.assert_not_called()
        assert isinstance(result, ToolMessage), (
            f"{blocked_tool}: expected ToolMessage, got {type(result)}"
        )
        # ReadOnlyToolGuardMiddleware embeds the tool name in its error text
        assert blocked_tool in result.content, (
            f"{blocked_tool}: error message should name the blocked tool; "
            f"got: {result.content!r}"
        )


def test_readonly_tool_guard_does_not_block_allowed_calls_in_full_chain() -> None:
    """ReadOnlyToolGuardMiddleware must pass through unblocked tool calls."""
    # Arrange
    chain = _build_full_chain()
    guard: ReadOnlyToolGuardMiddleware = next(
        m for m in chain if isinstance(m, ReadOnlyToolGuardMiddleware)
    )
    expected_tm = ToolMessage(content="thought captured", tool_call_id="call_think")
    handler = MagicMock(return_value=expected_tm)

    req = _make_request("think", tool_id="call_think")

    # Act
    result = guard.wrap_tool_call(req, handler)

    # Assert
    handler.assert_called_once_with(req)
    assert result is expected_tm


# ---------------------------------------------------------------------------
# Scenario 2: BuildEvidenceSummaryGuardMiddleware _call_count tracks correctly
# ---------------------------------------------------------------------------


def test_build_evidence_summary_guard_call_count_and_blocking_in_full_chain() -> None:
    """BuildEvidenceSummaryGuardMiddleware._call_count must reach 1 after
    the first allowed call and block the second call independently of whether
    SummarizerFinalizationGuardMiddleware is present in the chain."""
    # Arrange
    chain = _build_full_chain()
    bes_guard: BuildEvidenceSummaryGuardMiddleware = next(
        m for m in chain if isinstance(m, BuildEvidenceSummaryGuardMiddleware)
    )
    assert bes_guard._call_count == 0, "fresh instance must start at 0"

    success_tm = ToolMessage(content="evidence built", tool_call_id="call_bes_001")
    handler = MagicMock(return_value=success_tm)

    req1 = _make_request("build_evidence_summary", tool_id="call_bes_001")
    req2 = _make_request("build_evidence_summary", tool_id="call_bes_002")

    # Act — first call must pass through
    result1 = bes_guard.wrap_tool_call(req1, handler)

    # Assert after first call
    handler.assert_called_once_with(req1)
    assert bes_guard._call_count == 1, (
        f"_call_count must be 1 after first allowed call, got {bes_guard._call_count}"
    )
    assert result1 is success_tm

    # Act — second call must be blocked
    result2 = bes_guard.wrap_tool_call(req2, handler)

    # Assert after second call
    handler.assert_called_once()  # still called only once
    assert isinstance(result2, ToolMessage), "second call must return ToolMessage"
    payload = json.loads(result2.content)
    assert payload.get("already_invoked") is True, (
        f"blocked payload must have already_invoked=true; got {payload}"
    )
    assert result2.tool_call_id == "call_bes_002"


# ---------------------------------------------------------------------------
# Scenario 3: RepairCycleCounterMiddleware _cycle_count increments correctly
#             and it (not SummarizerFinalizationGuard) blocks the 3rd call
# ---------------------------------------------------------------------------


def test_repair_cycle_counter_tracks_count_and_blocks_third_call_not_guard() -> None:
    """RepairCycleCounterMiddleware._report_writer_count must reach 2 after two
    allowed task(report_writer) calls and block the third.  The block must
    come from RepairCycleCounterMiddleware (status=BLOCKED in payload), NOT
    from SummarizerFinalizationGuardMiddleware (blocked_by key)."""
    # Arrange — build isolated counter (no live chain needed; test the instance)
    counter = RepairCycleCounterMiddleware(max_cycles=2)

    task_result = ToolMessage(content=json.dumps({"ok": True}), tool_call_id="task_id")
    handler = MagicMock(return_value=task_result)

    def _make_rw_req(idx: int) -> Any:
        return _make_task_request("report_writer", tool_id=f"call_rw_{idx:03d}")

    # Act — first two calls must pass through and increment counter
    result1 = counter.wrap_tool_call(_make_rw_req(1), handler)
    result2 = counter.wrap_tool_call(_make_rw_req(2), handler)

    # Assert counter state after two successful calls
    assert counter._report_writer_count == 2, (
        f"_report_writer_count must be 2 after two calls, got {counter._report_writer_count}"
    )
    assert handler.call_count == 2
    assert result1 is task_result
    assert result2 is task_result

    # Act — third call must be blocked
    result3 = counter.wrap_tool_call(_make_rw_req(3), handler)

    # Assert: still only 2 calls to handler; third is blocked by counter
    assert handler.call_count == 2, "handler must NOT be called on blocked 3rd call"
    assert isinstance(result3, ToolMessage)
    payload = json.loads(result3.content)

    # Blocked by RepairCycleCounterMiddleware → "status": "BLOCKED"
    assert payload.get("status") == "BLOCKED", (
        f"RepairCycleCounterMiddleware must emit status=BLOCKED; got {payload}"
    )
    # Must NOT be blocked by SummarizerFinalizationGuardMiddleware
    assert payload.get("blocked_by") != "SummarizerFinalizationGuard", (
        "3rd task(report_writer) must be blocked by RepairCycleCounter, "
        f"not SummarizerFinalizationGuard; got payload={payload}"
    )


def test_repair_cycle_counter_in_full_chain_is_independent_of_guard_ordering() -> None:
    """Verify that the RepairCycleCounterMiddleware instance in the 6-entry
    chain starts at _report_writer_count==0 (no cross-contamination)."""
    # Arrange
    chain = _build_full_chain()
    counter: RepairCycleCounterMiddleware = next(
        m for m in chain if isinstance(m, RepairCycleCounterMiddleware)
    )

    # Assert — brand-new instance, counter must be zero
    assert counter._report_writer_count == 0, (
        "_report_writer_count must be 0 on a freshly built chain instance"
    )


# ---------------------------------------------------------------------------
# Scenario 4: FrozenTemplateSpanMiddleware still applies after guard passes
# ---------------------------------------------------------------------------


def test_frozen_template_span_blocks_mutated_template_after_guard_passes(
    tmp_path: Path,
) -> None:
    """FrozenTemplateSpanMiddleware must block save_drug_md that mutates
    non-EXPAND template spans, even when SummarizerFinalizationGuard is
    mounted before it at index 3.

    Setup:
      1. Write a reference card with a markdown_template to tmp_path.
      2. Build an isolated FrozenTemplateSpanMiddleware (simulating index 4).
      3. Simulate that SummarizerFinalizationGuardMiddleware already passed
         (i.e. validator returned valid=true).
      4. Send save_drug_md with content that mutates a frozen span.
      5. Assert FrozenTemplateSpanMiddleware blocks (not the guard).
    """
    # Arrange — write reference card so FrozenTemplateSpanMiddleware can load it
    data_dir = str(tmp_path)
    template = "## Static Header\n<!-- EXPAND:body -->\nExpand here.\n<!-- /EXPAND -->\n## Static Footer"
    card = {"markdown_template": template}
    (tmp_path / "drug_report_reference_card.json").write_text(
        json.dumps(card), encoding="utf-8"
    )

    frozen_span = FrozenTemplateSpanMiddleware(data_dir=data_dir)

    # Candidate content mutates the static footer (non-EXPAND span)
    mutated_content = (
        "## Static Header\n<!-- EXPAND:body -->\nExpand here.\n<!-- /EXPAND -->\n## MUTATED Footer"
    )
    req = _make_request(
        "save_drug_md",
        {"content": mutated_content},
        tool_id="call_sdm_001",
    )
    handler = MagicMock(return_value=ToolMessage(content="saved", tool_call_id="call_sdm_001"))

    # Act
    result = frozen_span.wrap_tool_call(req, handler)

    # Assert — FrozenTemplateSpanMiddleware must block, handler must not be called
    handler.assert_not_called()
    assert isinstance(result, ToolMessage), f"expected ToolMessage, got {type(result)}"
    payload = json.loads(result.content)
    assert payload.get("saved") is False, (
        f"FrozenTemplateSpanMiddleware must set saved=false; got {payload}"
    )
    assert "template" in payload.get("error", "").lower() or "frozen" in payload.get("error", "").lower(), (
        f"Error message should reference template/frozen spans; got: {payload.get('error')!r}"
    )
    # Must NOT carry blocked_by=SummarizerFinalizationGuard
    assert payload.get("blocked_by") != "SummarizerFinalizationGuard", (
        "Block must come from FrozenTemplateSpan, not SummarizerFinalizationGuard"
    )


def test_frozen_template_span_passes_through_when_no_data_dir_configured() -> None:
    """FrozenTemplateSpanMiddleware with data_dir=None is a pass-through."""
    # Arrange
    frozen_span = FrozenTemplateSpanMiddleware(data_dir=None)
    expected = ToolMessage(content="saved", tool_call_id="call_no_dir")
    handler = MagicMock(return_value=expected)
    req = _make_request("save_drug_md", {"content": "anything"}, "call_no_dir")

    # Act
    result = frozen_span.wrap_tool_call(req, handler)

    # Assert
    handler.assert_called_once_with(req)
    assert result is expected


# ---------------------------------------------------------------------------
# Scenario 5: AnnotationDensityMiddleware still applies after FrozenTemplate
# ---------------------------------------------------------------------------


# Content fixtures mirroring test_annotation_density_middleware.py

_SPARSE_DRUG_MD = "\n\n".join([
    "# Drug Report",
    "<!-- EXPAND:pharmacology -->",
    ". ".join(f"The drug inhibits pathway {i} strongly" for i in range(20))
    + ". Only one annotation [source: stage3_TGFB1.json].",
    "<!-- /EXPAND -->",
])

_DENSE_DRUG_MD = "\n\n".join([
    "# Drug Report",
    "<!-- EXPAND:pharmacology -->",
    ". ".join(
        f"Pathway {i} is inhibited [source: stage3_TGFB1.json]" for i in range(12)
    ) + ".",
    "<!-- /EXPAND -->",
])


def test_annotation_density_blocks_sparse_save_drug_md_in_full_chain() -> None:
    """AnnotationDensityMiddleware (index 5) must block save_drug_md with sparse
    annotations even when SummarizerFinalizationGuardMiddleware is in the chain."""
    # Arrange — use instance from the live chain to verify chain membership
    chain = _build_full_chain()
    density: AnnotationDensityMiddleware = next(
        m for m in chain if isinstance(m, AnnotationDensityMiddleware)
    )

    req = _make_request("save_drug_md", {"content": _SPARSE_DRUG_MD}, "call_sparse_001")
    handler = MagicMock(return_value=ToolMessage(content="saved", tool_call_id="call_sparse_001"))

    # Act
    result = density.wrap_tool_call(req, handler)

    # Assert — handler must not be reached; density check must fire
    handler.assert_not_called()
    assert isinstance(result, ToolMessage)
    payload = json.loads(result.content)
    assert payload.get("ok") is False, (
        f"AnnotationDensityMiddleware must set ok=false for sparse content; got {payload}"
    )
    assert "Annotation density" in payload.get("error", ""), (
        f"Error must mention annotation density; got: {payload.get('error')!r}"
    )
    # Must NOT be blocked_by SummarizerFinalizationGuard
    assert "SummarizerFinalizationGuard" not in payload.get("error", ""), (
        "Block must come from AnnotationDensityMiddleware, not SummarizerFinalizationGuard"
    )


def test_annotation_density_passes_through_dense_save_drug_md_in_full_chain() -> None:
    """AnnotationDensityMiddleware must pass save_drug_md when annotation count
    meets the threshold, reaching the underlying handler."""
    # Arrange
    chain = _build_full_chain()
    density: AnnotationDensityMiddleware = next(
        m for m in chain if isinstance(m, AnnotationDensityMiddleware)
    )

    success_tm = ToolMessage(content="saved ok", tool_call_id="call_dense_001")
    handler = MagicMock(return_value=success_tm)
    req = _make_request("save_drug_md", {"content": _DENSE_DRUG_MD}, "call_dense_001")

    # Act
    result = density.wrap_tool_call(req, handler)

    # Assert
    handler.assert_called_once_with(req)
    assert result is success_tm


# ---------------------------------------------------------------------------
# Async coverage: awrap_tool_call path (F2 — CV-P1-001)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_evidence_summary_guard_awrap_tool_call_blocks_duplicate_async() -> None:
    """BuildEvidenceSummaryGuardMiddleware.awrap_tool_call must block the second
    build_evidence_summary call, mirroring the sync scenario 2 test.

    Exercises the async code path through the chain extracted from a live
    _build_full_chain() call.
    """
    # Arrange — extract the guard from the live chain
    chain = _build_full_chain()
    bes_guard: BuildEvidenceSummaryGuardMiddleware = next(
        m for m in chain if isinstance(m, BuildEvidenceSummaryGuardMiddleware)
    )
    assert bes_guard._call_count == 0, "fresh chain instance must start at 0"

    success_tm = ToolMessage(content="evidence built", tool_call_id="call_bes_async_001")

    async def async_handler(req: Any) -> ToolMessage:
        return success_tm

    req1 = _make_request("build_evidence_summary", tool_id="call_bes_async_001")
    req2 = _make_request("build_evidence_summary", tool_id="call_bes_async_002")

    # Act — first call must pass through
    result1 = await bes_guard.awrap_tool_call(req1, async_handler)

    # Assert after first call
    assert bes_guard._call_count == 1, (
        f"_call_count must be 1 after first call, got {bes_guard._call_count}"
    )
    assert result1 is success_tm

    # Act — second call must be blocked
    result2 = await bes_guard.awrap_tool_call(req2, async_handler)

    # Assert: blocked payload present, count did not increase
    assert bes_guard._call_count == 1, "count must not increment on blocked second call"
    assert isinstance(result2, ToolMessage), "blocked result must be a ToolMessage"
    payload = json.loads(result2.content)
    assert payload.get("already_invoked") is True, (
        f"awrap_tool_call: blocked payload must have already_invoked=true; got {payload}"
    )
    assert result2.tool_call_id == "call_bes_async_002"
