"""TC-6: Structural assertions for CriticOutput TypedDict (T18).

Tests verify:
- get_type_hints(CriticOutput) keys match the spec
- get_type_hints(Finding) includes the new additive fields
- get_type_hints(ClaimVerdict) matches spec
- sample_v1.json fixture conforms to the schema (key presence + value types)
"""

import json
from pathlib import Path
from typing import get_type_hints

import pytest

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "critic_outputs" / "sample_v1.json"
)


# ---------------------------------------------------------------------------
# Imports (will fail RED until critic_schema.py exists)
# ---------------------------------------------------------------------------

from src.agents.drug_target.subagents.critic_schema import (  # noqa: E402
    CriticOutput,
    Finding,
    ClaimVerdict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


# ---------------------------------------------------------------------------
# CriticOutput key structure
# ---------------------------------------------------------------------------


def test_critic_output_has_required_keys():
    """CriticOutput TypedDict must have all 7 specified keys."""
    hints = get_type_hints(CriticOutput)
    required = {
        "passed",
        "severity_counts",
        "checked_gates",
        "findings",
        "repair_instructions",
        "claim_verdicts",
    }
    assert required.issubset(hints.keys()), (
        f"Missing keys: {required - hints.keys()}"
    )


def test_finding_has_new_additive_fields():
    """Finding TypedDict must include claim_text and source_field (T18 additions)."""
    hints = get_type_hints(Finding)
    assert "claim_text" in hints, "Finding must have 'claim_text'"
    assert "source_field" in hints, "Finding must have 'source_field'"


def test_finding_has_legacy_fields():
    """Finding TypedDict must preserve all pre-existing fields."""
    hints = get_type_hints(Finding)
    legacy = {"severity", "issue", "evidence", "repair"}
    assert legacy.issubset(hints.keys()), (
        f"Missing legacy keys: {legacy - hints.keys()}"
    )


def test_claim_verdict_has_required_keys():
    """ClaimVerdict TypedDict must have all 5 specified keys."""
    hints = get_type_hints(ClaimVerdict)
    required = {"section", "claim_text", "verdict", "source_field", "reason"}
    assert required.issubset(hints.keys()), (
        f"Missing keys: {required - hints.keys()}"
    )


# ---------------------------------------------------------------------------
# Fixture conformance
# ---------------------------------------------------------------------------


def test_fixture_conforms_to_critic_output_keys():
    """sample_v1.json must contain all CriticOutput keys."""
    data = _load_fixture()
    hints = get_type_hints(CriticOutput)
    for key in hints:
        assert key in data, f"Fixture missing key: {key}"


def test_fixture_findings_have_new_fields():
    """Each finding in sample_v1.json must have claim_text and source_field."""
    data = _load_fixture()
    for i, finding in enumerate(data.get("findings", [])):
        assert "claim_text" in finding, f"findings[{i}] missing 'claim_text'"
        assert "source_field" in finding, f"findings[{i}] missing 'source_field'"


def test_fixture_claim_verdicts_structure():
    """Each claim_verdict entry must have all ClaimVerdict keys."""
    data = _load_fixture()
    hints = get_type_hints(ClaimVerdict)
    for i, cv in enumerate(data.get("claim_verdicts", [])):
        for key in hints:
            assert key in cv, f"claim_verdicts[{i}] missing key: {key}"


def test_fixture_passed_is_bool():
    data = _load_fixture()
    assert isinstance(data["passed"], bool)


def test_fixture_repair_instructions_is_list():
    data = _load_fixture()
    assert isinstance(data["repair_instructions"], list)


def test_fixture_checked_gates_is_list():
    data = _load_fixture()
    assert isinstance(data["checked_gates"], list)
