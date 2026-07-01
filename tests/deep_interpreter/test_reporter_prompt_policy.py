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


def _extract_phase47_block() -> str:
    match = re.search(
        r"### Phase 4\.7:.*?(?=### Phase 5\.0:)",
        REPORTER_PROMPT,
        flags=re.DOTALL,
    )
    assert match, "Could not locate Phase 4.7 block in REPORTER prompt"
    return match.group(0)


def test_reporter_phase47_reads_part4_synthesis_before_drug_md():
    block = _extract_phase47_block()

    assert "part4_therapeutic_synthesis.md" in block
    assert "drug.md" in block
    assert block.index("part4_therapeutic_synthesis.md") < block.index("drug.md")


def test_reporter_phase47_reads_part4_sources_from_virtual_root():
    block = _extract_phase47_block()

    assert 'read_file("/part4_therapeutic_synthesis.md")' in block
    assert 'read_file("/drug.md")' in block
    assert 'read_file(f"{data_path.strip()}/part4_therapeutic_synthesis.md")' not in block
    assert 'read_file(f"{data_path.strip()}/drug.md")' not in block


def test_reporter_phase47_treats_part4_as_canonical_and_drug_md_as_supporting():
    block = _extract_phase47_block().lower()

    assert "canonical" in block
    assert "supporting" in block
    assert "prefer part4_therapeutic_synthesis.md" in block
    assert "do not duplicate" in block


def test_reporter_template_mode_uses_part4_synthesis_source():
    prompt = REPORTER_PROMPT

    assert '"template_mode": "comprehensive"' in prompt
    assert "part4_therapeutic_synthesis.md" in prompt
    assert "Therapeutic Implications tab" in prompt


def test_reporter_phase5_uses_comprehensive_template_mode():
    assert '"template_mode": "comprehensive"' in REPORTER_PROMPT
    assert '"part1_html":' not in REPORTER_PROMPT
    assert '"part2_html":' not in REPORTER_PROMPT
    assert '"part3_html":' not in REPORTER_PROMPT
    assert '"summary_html":' not in REPORTER_PROMPT
    assert '"therapeutic_html":' not in REPORTER_PROMPT


def test_reporter_phase5_keeps_therapeutic_source_tracking():
    assert "part4_therapeutic_synthesis.md" in REPORTER_PROMPT
    assert "canonical_source" in REPORTER_PROMPT
    assert "supporting_source" in REPORTER_PROMPT


def test_reporter_rag_validation_passes_explicit_data_dir():
    prompt = REPORTER_PROMPT

    assert "prepare_rag_literature(" in prompt
    assert re.search(
        r"validate_claim_fulltext\s*\([^)]*data_dir=data_path\.strip\(\)",
        prompt,
        flags=re.DOTALL,
    ), "REPORTER validate_claim_fulltext calls must pass explicit data_dir"
