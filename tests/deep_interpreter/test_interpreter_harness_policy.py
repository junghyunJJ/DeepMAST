"""Harness policy tests for standalone INTERPRETER Part 1/2/3 messages.

Mirrors the production INTERPRETER prompt policy:
- think_tool reference appears BEFORE validate_quality reference in the
  MANDATORY WORKFLOW text
- prioritize_top_lr_pairs is NOT mentioned anywhere in Part 3 (closes the
  pre-existing forbidden-tool regression at test_part3_interpreter.py:64)
"""

from __future__ import annotations

import pytest

from tests.test_part1_interpreter import PART1_MESSAGE
from tests.test_part2_interpreter import PART2_MESSAGE
from tests.test_part3_interpreter import PART3_MESSAGE


def _message_text(message: dict) -> str:
    return message["messages"][0]["content"]


@pytest.mark.parametrize(
    "label,message",
    [
        ("part1", PART1_MESSAGE),
        ("part2", PART2_MESSAGE),
        ("part3", PART3_MESSAGE),
    ],
)
def test_harness_think_tool_before_validate_quality(label, message):
    text = _message_text(message)
    assert "think_tool" in text, f"{label} harness must reference think_tool"
    assert "validate_quality" in text, f"{label} harness must reference validate_quality"
    assert text.index("think_tool") < text.index("validate_quality"), (
        f"{label} MANDATORY WORKFLOW must call think_tool BEFORE validate_quality "
        f"(Phase 4 Steps A-E ordering)."
    )


def test_part3_harness_has_no_prioritize_top_lr_pairs():
    """Closes the forbidden-tool regression at tests/test_part3_interpreter.py:64.

    The production prompt forbids this tool (see prompts.py:614-616); it was
    executed by the wrapper (Step 9.5) before the interpreter runs.
    """
    text = _message_text(PART3_MESSAGE)
    assert "prioritize_top_lr_pairs" not in text, (
        "Part 3 harness message must NOT reference prioritize_top_lr_pairs — "
        "it is a forbidden tool for INTERPRETER (wrapper Step 9.5 already executed "
        "it; use load_analysis_data to read target_assessment.json instead)."
    )


@pytest.mark.parametrize(
    "label,message",
    [
        ("part1", PART1_MESSAGE),
        ("part2", PART2_MESSAGE),
        ("part3", PART3_MESSAGE),
    ],
)
def test_harness_mentions_score_threshold_0_8(label, message):
    """Harness instructs the model to use score_threshold=0.8 on think_tool."""
    text = _message_text(message)
    assert "score_threshold=0.8" in text, (
        f"{label} harness must pass score_threshold=0.8 at the think_tool call site."
    )


@pytest.mark.parametrize(
    "label,message",
    [
        ("part1", PART1_MESSAGE),
        ("part2", PART2_MESSAGE),
        ("part3", PART3_MESSAGE),
    ],
)
def test_harness_mentions_use_llm_false(label, message):
    text = _message_text(message)
    assert "use_llm=False" in text, (
        f"{label} harness must pass use_llm=False on validate_quality to avoid "
        f"duplicate reflection-tool MCP calls."
    )
