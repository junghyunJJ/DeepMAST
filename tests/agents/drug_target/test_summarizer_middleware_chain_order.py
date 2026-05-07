"""Wire-up regression: assert the summarizer middleware chain has exactly 6
entries in the canonical order defined by Plan §2.1.B.

Order:
  0  ReadOnlyToolGuardMiddleware
  1  BuildEvidenceSummaryGuardMiddleware
  2  RepairCycleCounterMiddleware
  3  SummarizerFinalizationGuardMiddleware   ← inserted in Task #10
  4  FrozenTemplateSpanMiddleware
  5  AnnotationDensityMiddleware

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
    FrozenTemplateSpanMiddleware,
    RepairCycleCounterMiddleware,
    SummarizerFinalizationGuardMiddleware,
)


_EXPECTED_ORDER = [
    ReadOnlyToolGuardMiddleware,
    BuildEvidenceSummaryGuardMiddleware,
    RepairCycleCounterMiddleware,
    SummarizerFinalizationGuardMiddleware,
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


def test_middleware_chain_has_six_entries(middleware_chain: list) -> None:
    assert len(middleware_chain) == 6, (
        f"Expected 6 middleware entries, got {len(middleware_chain)}: "
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


def test_finalization_guard_before_frozen_template_span(middleware_chain: list) -> None:
    """Guard at index 3, FrozenTemplateSpan at index 4 — guard must precede span."""
    guard_idx = next(
        (i for i, m in enumerate(middleware_chain) if isinstance(m, SummarizerFinalizationGuardMiddleware)),
        None,
    )
    span_idx = next(
        (i for i, m in enumerate(middleware_chain) if isinstance(m, FrozenTemplateSpanMiddleware)),
        None,
    )
    assert guard_idx is not None, "SummarizerFinalizationGuardMiddleware not found in chain"
    assert span_idx is not None, "FrozenTemplateSpanMiddleware not found in chain"
    assert guard_idx < span_idx, (
        f"SummarizerFinalizationGuardMiddleware (idx={guard_idx}) must come BEFORE "
        f"FrozenTemplateSpanMiddleware (idx={span_idx})"
    )
