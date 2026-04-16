"""Prompt policy tests for the REPORTER subagent.

Verifies that REPORTER's Phase 4.5 prompt keeps think_tool as the active
reflection/planning mechanism (Step 2 strategic planning + Step 4 quality
reflection) AND that validate_quality is NOT promoted to a mandatory
completion gate.
"""

from __future__ import annotations

import re

import pytest

from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS


REPORTER_PROMPT = SUBAGENT_PROMPTS["reporter"]


def _extract_phase45_step_block(step_header: str) -> str:
    """Extract a specific Phase 4.5 step block from REPORTER prompt.

    Steps are marked `#### Step N: Title`.
    """
    pattern = rf"#### {re.escape(step_header)}.*?(?=#### Step|### Phase|\Z)"
    match = re.search(pattern, REPORTER_PROMPT, flags=re.DOTALL)
    assert match, f"Could not locate '#### {step_header}' block in REPORTER prompt"
    return match.group(0)


def test_phase45_step2_strategic_planning_uses_think_tool():
    block = _extract_phase45_step_block("Step 2: Strategic Planning (think_tool x3)")
    assert "think_tool" in block, (
        "Phase 4.5 Step 2 must keep think_tool as the strategic-planning mechanism."
    )
    # At least 3 invocations implied by 'x3' title; confirm multiple references.
    assert block.count("think_tool") >= 3, (
        f"Phase 4.5 Step 2 title says 'think_tool x3' but block contains "
        f"{block.count('think_tool')} references."
    )


def test_phase45_step4_quality_reflection_uses_think_tool():
    block = _extract_phase45_step_block("Step 4: Quality Reflection (think_tool)")
    assert "think_tool" in block, (
        "Phase 4.5 Step 4 must keep think_tool as the quality reflection mechanism."
    )


def test_reporter_does_not_mandate_validate_quality_gate():
    """REPORTER's validate_quality must remain secondary/non-gating.

    Forbidden patterns that would indicate REPORTER was promoted to a hard gate:
    - 'validate_quality' followed by 'must', 'required', or 'gate' within 40 chars.
    """
    forbidden_patterns = [
        r"validate_quality[^.\n]{0,40}\bmust\b",
        r"validate_quality[^.\n]{0,40}\brequired\b",
        r"validate_quality[^.\n]{0,40}\bgate\b",
        r"mandatory\b[^.\n]{0,40}validate_quality",
        r"MANDATORY\b[^.\n]{0,40}validate_quality",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, REPORTER_PROMPT, flags=re.IGNORECASE | re.DOTALL), (
            f"REPORTER prompt must NOT gate on validate_quality. Forbidden pattern "
            f"matched: {pattern!r}"
        )


def test_reporter_still_references_validate_quality_as_secondary():
    """validate_quality must remain available as an objective quality tool (secondary)."""
    # The Tools Available section lists it; make sure it is still present but
    # without promotion to a gate.
    assert "validate_quality" in REPORTER_PROMPT, (
        "REPORTER prompt should still reference validate_quality as an available "
        "secondary tool, even though it is not a mandatory gate."
    )


def test_reporter_think_tool_is_prompt_mandatory_not_runtime_enforced():
    """Both strategic-planning and quality-reflection think_tool calls remain prompt-level."""
    # Sanity: the prompt contains the two key think_tool usages and does not
    # reference a middleware/hook that would hard-enforce them.
    assert "think_tool" in _extract_phase45_step_block("Step 2: Strategic Planning (think_tool x3)")
    assert "think_tool" in _extract_phase45_step_block("Step 4: Quality Reflection (think_tool)")
    # No middleware/gate language around think_tool in REPORTER.
    assert not re.search(
        r"middleware[^.\n]{0,40}think_tool|think_tool[^.\n]{0,40}middleware",
        REPORTER_PROMPT,
        flags=re.IGNORECASE,
    ), "REPORTER think_tool usage must remain prompt-level, not runtime-enforced."
