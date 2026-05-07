"""Wire-up regression: assert the summarizer middleware chain has exactly 7
entries in the canonical order defined by Plan §2.1.B (updated for sanitizer).

Order:
  0  ReadOnlyToolGuardMiddleware
  1  BuildEvidenceSummaryGuardMiddleware
  2  RepairCycleCounterMiddleware
  3  SummarizerFinalizationGuardMiddleware
  4  DrugMdSaveSanitizerMiddleware           ← inserted here (sanitize before frozen-span)
  5  FrozenTemplateSpanMiddleware
  6  AnnotationDensityMiddleware

The factory (create_summarizer_agent) calls create_deep_agent at construction
time, which requires a live model endpoint.  This test monkeypatches
create_deep_agent so the middleware list can be inspected without any LLM call.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.deep_interpreter.middleware.write_file_guard import (
    ReadOnlyToolGuardMiddleware,
)
from src.agents.drug_target.subagents.summarizer.middleware import (
    AnnotationDensityMiddleware,
    BuildEvidenceSummaryGuardMiddleware,
    DrugMdSaveSanitizerMiddleware,
    FrozenTemplateSpanMiddleware,
    RepairCycleCounterMiddleware,
    SummarizerFinalizationGuardMiddleware,
)


_EXPECTED_ORDER = [
    ReadOnlyToolGuardMiddleware,
    BuildEvidenceSummaryGuardMiddleware,
    RepairCycleCounterMiddleware,
    SummarizerFinalizationGuardMiddleware,
    DrugMdSaveSanitizerMiddleware,
    FrozenTemplateSpanMiddleware,
    AnnotationDensityMiddleware,
]


def _capture_middleware() -> list:
    """Invoke create_summarizer_agent with create_deep_agent patched.

    Returns the middleware list that was passed to create_deep_agent.
    """
    captured: list = []

    fake_agent = MagicMock(spec=["with_config", "invoke", "ainvoke", "stream", "astream"])
    fake_agent.with_config.return_value = fake_agent

    def _fake_create_deep_agent(**kwargs):  # noqa: ANN202
        captured.extend(kwargs.get("middleware", []))
        return fake_agent

    # Import here so the patch target is the name used inside agent.py.
    import src.agents.drug_target.subagents.summarizer.agent as agent_module

    with patch.object(agent_module, "create_deep_agent", side_effect=_fake_create_deep_agent):
        from src.agents.drug_target.subagents.summarizer.agent import (
            create_summarizer_agent,
        )

        create_summarizer_agent()

    return captured


@pytest.fixture(scope="module")
def middleware_chain() -> list:
    return _capture_middleware()


def test_middleware_chain_has_seven_entries(middleware_chain: list) -> None:
    assert len(middleware_chain) == 7, (
        f"Expected 7 middleware entries, got {len(middleware_chain)}: "
        + ", ".join(type(m).__name__ for m in middleware_chain)
    )


def test_middleware_chain_order_matches_plan(middleware_chain: list) -> None:
    actual_types = [type(m) for m in middleware_chain]
    assert actual_types == _EXPECTED_ORDER, (
        "Middleware order diverged from Plan §2.1.B.\n"
        f"Expected: {[c.__name__ for c in _EXPECTED_ORDER]}\n"
        f"Got:      {[c.__name__ for c in actual_types]}"
    )


def test_finalization_guard_is_at_index_3(middleware_chain: list) -> None:
    assert isinstance(middleware_chain[3], SummarizerFinalizationGuardMiddleware), (
        f"Index 3 should be SummarizerFinalizationGuardMiddleware, "
        f"got {type(middleware_chain[3]).__name__}"
    )


def test_sanitizer_is_at_index_4(middleware_chain: list) -> None:
    assert isinstance(middleware_chain[4], DrugMdSaveSanitizerMiddleware), (
        f"Index 4 should be DrugMdSaveSanitizerMiddleware, "
        f"got {type(middleware_chain[4]).__name__}"
    )


def test_frozen_template_span_is_at_index_5(middleware_chain: list) -> None:
    assert isinstance(middleware_chain[5], FrozenTemplateSpanMiddleware), (
        f"Index 5 should be FrozenTemplateSpanMiddleware, "
        f"got {type(middleware_chain[5]).__name__}"
    )


def test_annotation_density_is_at_index_6(middleware_chain: list) -> None:
    assert isinstance(middleware_chain[6], AnnotationDensityMiddleware), (
        f"Index 6 should be AnnotationDensityMiddleware, "
        f"got {type(middleware_chain[6]).__name__}"
    )


def test_repair_cycle_counter_before_finalization_guard(middleware_chain: list) -> None:
    """Counter at index 2, guard at index 3 — counter must precede guard."""
    counter_idx = next(
        (i for i, m in enumerate(middleware_chain) if isinstance(m, RepairCycleCounterMiddleware)),
        None,
    )
    guard_idx = next(
        (i for i, m in enumerate(middleware_chain) if isinstance(m, SummarizerFinalizationGuardMiddleware)),
        None,
    )
    assert counter_idx is not None, "RepairCycleCounterMiddleware not found in chain"
    assert guard_idx is not None, "SummarizerFinalizationGuardMiddleware not found in chain"
    assert counter_idx < guard_idx, (
        f"RepairCycleCounterMiddleware (idx={counter_idx}) must come BEFORE "
        f"SummarizerFinalizationGuardMiddleware (idx={guard_idx})"
    )


def test_sanitizer_before_frozen_template_span(middleware_chain: list) -> None:
    """Sanitizer at index 4, FrozenTemplateSpan at index 5 — sanitizer must precede span."""
    sanitizer_idx = next(
        (i for i, m in enumerate(middleware_chain) if isinstance(m, DrugMdSaveSanitizerMiddleware)),
        None,
    )
    span_idx = next(
        (i for i, m in enumerate(middleware_chain) if isinstance(m, FrozenTemplateSpanMiddleware)),
        None,
    )
    assert sanitizer_idx is not None, "DrugMdSaveSanitizerMiddleware not found in chain"
    assert span_idx is not None, "FrozenTemplateSpanMiddleware not found in chain"
    assert sanitizer_idx < span_idx, (
        f"DrugMdSaveSanitizerMiddleware (idx={sanitizer_idx}) must come BEFORE "
        f"FrozenTemplateSpanMiddleware (idx={span_idx})"
    )


def test_finalization_guard_before_sanitizer(middleware_chain: list) -> None:
    """Guard at index 3, sanitizer at index 4 — guard must precede sanitizer."""
    guard_idx = next(
        (i for i, m in enumerate(middleware_chain) if isinstance(m, SummarizerFinalizationGuardMiddleware)),
        None,
    )
    sanitizer_idx = next(
        (i for i, m in enumerate(middleware_chain) if isinstance(m, DrugMdSaveSanitizerMiddleware)),
        None,
    )
    assert guard_idx is not None, "SummarizerFinalizationGuardMiddleware not found in chain"
    assert sanitizer_idx is not None, "DrugMdSaveSanitizerMiddleware not found in chain"
    assert guard_idx < sanitizer_idx, (
        f"SummarizerFinalizationGuardMiddleware (idx={guard_idx}) must come BEFORE "
        f"DrugMdSaveSanitizerMiddleware (idx={sanitizer_idx})"
    )
