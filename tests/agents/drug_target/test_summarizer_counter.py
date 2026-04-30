"""TC-6c: Programmatic repair-loop counter (T16).

Tests verify that the summarizer loop orchestration emits BLOCKED
after 2 critic cycles when validate_drug_md still reports P0 findings.

The test uses a typed fake critic (always FAIL with one P0 finding)
and a typed fake validate_drug_md (always returns a P0 issue).

No live LLM or filesystem is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Will fail RED until run_summarizer_loop exists in configs.py
from src.agents.drug_target.subagents.configs import run_summarizer_loop


# ---------------------------------------------------------------------------
# Typed fake return values — match actual tool response shapes
# ---------------------------------------------------------------------------

_FAILING_VALIDATE_RESULT = {
    "valid": False,
    "issue_count": 1,
    "issues": [
        {
            "code": "DRUG_NOT_IN_EVIDENCE",
            "severity": "critical",
            "message": "Drug 'FakeDrug' not found in local evidence.",
            "location": "Section 1",
            "evidence": {},
        }
    ],
    "checks": {},
    "sources": [],
}

_P0_CRITIC_OUTPUT = {
    "passed": False,
    "severity_counts": {"P0": 1, "P1": 0, "P2": 0, "P3": 0},
    "checked_gates": ["validate_drug_md", "evidence_grounding"],
    "findings": [
        {
            "severity": "P0",
            "issue": "Ungrounded drug claim.",
            "evidence": "Not in resolved_drugs.json",
            "repair": "Remove the claim.",
            "claim_text": "FakeDrug cures cancer.",
            "source_field": "resolved_drugs",
        }
    ],
    "repair_instructions": ["Remove the claim."],
    "claim_verdicts": [],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_loop_emits_blocked_after_two_failing_cycles(tmp_path):
    """After 2 repair cycles with persistent P0, loop must return BLOCKED status."""
    result = run_summarizer_loop(
        data_dir=str(tmp_path),
        fake_validate_result=_FAILING_VALIDATE_RESULT,
        fake_critic_output=_P0_CRITIC_OUTPUT,
        max_cycles=2,
    )
    assert result["status"] == "BLOCKED", (
        f"Expected BLOCKED after 2 failing cycles, got: {result['status']!r}"
    )
    assert "blocker" in result, "Result must include 'blocker' key"
    assert result["repair_cycles"] == 2, (
        f"Expected repair_cycles=2, got {result['repair_cycles']}"
    )


def test_loop_does_not_block_when_critic_passes(tmp_path):
    """When critic passes on first attempt, loop must NOT emit BLOCKED."""
    passing_critic = {**_P0_CRITIC_OUTPUT, "passed": True, "findings": []}
    passing_validate = {**_FAILING_VALIDATE_RESULT, "valid": True, "issue_count": 0, "issues": []}

    result = run_summarizer_loop(
        data_dir=str(tmp_path),
        fake_validate_result=passing_validate,
        fake_critic_output=passing_critic,
        max_cycles=2,
    )
    assert result["status"] != "BLOCKED", (
        f"Should not be BLOCKED when critic passes: {result}"
    )


def test_loop_respects_max_cycles_boundary(tmp_path):
    """Loop must not exceed max_cycles regardless of failures."""
    result = run_summarizer_loop(
        data_dir=str(tmp_path),
        fake_validate_result=_FAILING_VALIDATE_RESULT,
        fake_critic_output=_P0_CRITIC_OUTPUT,
        max_cycles=3,
    )
    assert result["repair_cycles"] <= 3, (
        f"repair_cycles {result['repair_cycles']} exceeded max_cycles=3"
    )


def test_loop_includes_p0_findings_in_blocker(tmp_path):
    """BLOCKED result must carry the P0 findings from the final critic output."""
    result = run_summarizer_loop(
        data_dir=str(tmp_path),
        fake_validate_result=_FAILING_VALIDATE_RESULT,
        fake_critic_output=_P0_CRITIC_OUTPUT,
        max_cycles=2,
    )
    assert result["status"] == "BLOCKED"
    blocker = result["blocker"]
    # blocker must reference P0 findings (either as list or serialized string)
    blocker_text = str(blocker)
    assert "P0" in blocker_text or "Ungrounded" in blocker_text, (
        f"Blocker should contain P0 finding info, got: {blocker_text!r}"
    )
