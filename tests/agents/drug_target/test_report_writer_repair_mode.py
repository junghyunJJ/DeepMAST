"""Regression tests for Fix 1 (REPORT_WRITER_PROMPT repair-mode branch)
and Fix 3 (SUMMARIZER_PROMPT dedup + Section-4 gate).

All tests are deterministic — no live LLM is invoked.
Tests operate at:
  - Prompt-text level: assert literal instruction strings are present in prompts.
  - Pure-Python logic level: assert synthesize_repair_instructions helper behavior.

RED: these tests are written BEFORE implementation so they fail initially.
GREEN: they pass after Fix 1 and Fix 3 are applied.
"""

from __future__ import annotations

import pytest

# Prompt constants (Fix 1 assertions)
from src.agents.drug_target.subagents.prompts import (
    REPORT_WRITER_PROMPT,
    SUMMARIZER_PROMPT,
)

# Pure-Python synthesis helper (Fix 3 assertions)
from src.agents.drug_target.subagents.configs import synthesize_repair_instructions


# =============================================================================
# Fix 1 — REPORT_WRITER_PROMPT repair-mode branch (prompt-text assertions)
# =============================================================================


def test_report_writer_repair_branch_contains_repair_mode_heading():
    """Fix 1 — REPORT_WRITER_PROMPT must contain the '## REPAIR MODE' heading
    so the writer can distinguish repair invocations from initial-write runs."""
    assert "## REPAIR MODE" in REPORT_WRITER_PROMPT, (
        "REPORT_WRITER_PROMPT is missing the '## REPAIR MODE' section heading. "
        "Without this heading the writer cannot distinguish a repair call from "
        "an initial-write call, causing it to re-run build_evidence_summary on "
        "every repair invocation (the oscillation root cause)."
    )


def test_report_writer_repair_branch_instructs_load_not_build():
    """Fix 1 — repair branch must instruct 'load_evidence_files(\"drug.md\")'
    and must explicitly forbid calling build_evidence_summary again."""
    assert 'load_evidence_files("drug.md")' in REPORT_WRITER_PROMPT, (
        "REPORT_WRITER_PROMPT repair branch must instruct the writer to call "
        'load_evidence_files("drug.md") to read the existing report, not '
        "rebuild from scratch."
    )
    assert "DO NOT call build_evidence_summary" in REPORT_WRITER_PROMPT, (
        "REPORT_WRITER_PROMPT repair branch must contain the literal instruction "
        "'DO NOT call build_evidence_summary' to prevent the Phase-1 re-build "
        "that discards all prior EXPAND fills and [source:] annotations."
    )


# =============================================================================
# Fix 3 — SUMMARIZER_PROMPT: ## REPAIR MODE marker forwarded to writer
# =============================================================================


def test_summarizer_includes_repair_mode_marker_instruction():
    """Fix 3 — when the summarizer re-invokes report_writer for repairs,
    the SUMMARIZER_PROMPT must instruct it to prepend '## REPAIR MODE'
    so the writer's Fix-1 branch triggers reliably."""
    assert "## REPAIR MODE" in SUMMARIZER_PROMPT, (
        "SUMMARIZER_PROMPT must instruct the summarizer to prepend '## REPAIR MODE' "
        "to the repair instruction payload it sends to report_writer. Without this "
        "the writer cannot detect it is in repair mode."
    )


# =============================================================================
# Fix 3 — synthesize_repair_instructions pure-Python helper
# =============================================================================


def test_synthesize_repair_instructions_deduplicates_same_claim_source_pair():
    """Fix 3 — duplicate (claim_text, source_field) pairs must collapse to one
    instruction. Many critic FAILs target the same source-field gap; emitting
    duplicate repair instructions causes redundant report_writer invocations."""
    claim_verdicts = [
        {"verdict": "FAIL", "claim_text": "Drug X is approved.", "source_field": "first_approval"},
        {"verdict": "FAIL", "claim_text": "Drug X is approved.", "source_field": "first_approval"},
        {"verdict": "FAIL", "claim_text": "Drug X is approved.", "source_field": "first_approval"},
    ]
    instructions = synthesize_repair_instructions(claim_verdicts)
    assert len(instructions) == 1, (
        f"Expected 1 deduplicated instruction, got {len(instructions)}: {instructions}"
    )


def test_synthesize_repair_instructions_skips_section4_verdicts():
    """Fix 3 — claim_verdicts with section == 'section_4' must be filtered out.
    Section 4 prose originates from hypothesis_report.json and is not editable
    by report_writer; passing these as repair instructions causes an oscillation
    loop because the writer cannot resolve them."""
    claim_verdicts = [
        {
            "verdict": "FAIL",
            "claim_text": "Hypothesis claim about ITGB2.",
            "source_field": "hypothesis",
            "section": "section_4",
        },
        {
            "verdict": "FAIL",
            "claim_text": "Drug Y approval year wrong.",
            "source_field": "first_approval",
            "section": "section_3",
        },
    ]
    instructions = synthesize_repair_instructions(claim_verdicts)
    # Only the section_3 entry should produce a repair instruction
    assert len(instructions) == 1, (
        f"Expected 1 instruction (section_4 filtered), got {len(instructions)}: {instructions}"
    )
    assert "hypothesis" not in str(instructions).lower() or "Drug Y" in str(instructions), (
        "section_4 hypothesis verdict must not appear in repair instructions"
    )


def test_synthesize_repair_instructions_returns_empty_for_all_section4():
    """Fix 3 — if every FAIL verdict is in section_4, synthesize_repair_instructions
    must return an empty list, which tells the summarizer to skip re-invoking
    report_writer (no oscillation)."""
    claim_verdicts = [
        {
            "verdict": "FAIL",
            "claim_text": "Hypothesis claim A.",
            "source_field": "hypothesis",
            "section": "section_4",
        },
        {
            "verdict": "FAIL",
            "claim_text": "Hypothesis claim B.",
            "source_field": "hypothesis",
            "section": "section_4",
        },
    ]
    instructions = synthesize_repair_instructions(claim_verdicts)
    assert instructions == [], (
        f"Expected empty list when all verdicts are section_4, got: {instructions}"
    )


def test_synthesize_repair_instructions_ignores_pass_verdicts():
    """Fix 3 — PASS verdicts must not generate repair instructions."""
    claim_verdicts = [
        {"verdict": "PASS", "claim_text": "Drug Z is safe.", "source_field": "safety_notes"},
        {"verdict": "FAIL", "claim_text": "Drug Z approval wrong.", "source_field": "first_approval"},
    ]
    instructions = synthesize_repair_instructions(claim_verdicts)
    assert len(instructions) == 1, (
        f"Expected only 1 instruction from 1 FAIL verdict, got {len(instructions)}: {instructions}"
    )


def test_synthesize_repair_instructions_deduplicates_mixed_sections():
    """Fix 3 — dedup and section_4 gate must both apply together:
    two duplicate section_3 FAILs + one section_4 FAIL should produce exactly 1 instruction."""
    claim_verdicts = [
        {
            "verdict": "FAIL",
            "claim_text": "Drug A year.",
            "source_field": "first_approval",
            "section": "section_3",
        },
        {
            "verdict": "FAIL",
            "claim_text": "Drug A year.",
            "source_field": "first_approval",
            "section": "section_3",
        },
        {
            "verdict": "FAIL",
            "claim_text": "Hyp claim.",
            "source_field": "hypothesis",
            "section": "section_4",
        },
    ]
    instructions = synthesize_repair_instructions(claim_verdicts)
    assert len(instructions) == 1, (
        f"Expected 1 instruction after dedup+section4 gate, got {len(instructions)}: {instructions}"
    )
