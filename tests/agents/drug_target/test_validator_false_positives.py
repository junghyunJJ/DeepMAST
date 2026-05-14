"""Regression tests for two validator false-positive bugs identified in the
res_ipf_openai2 run (SUMMARIZER_STATUS: FAIL trace).

F-A: DECIMAL_RUBRIC_SCORES regex over-matches STRING PPI confidence scores.
     "the STRING combined score 0.999 predicts…" should NOT raise the issue.
     "combined_total: 5.5" MUST still raise the issue (legitimate catch).

F-B: _MOA_UNAVAILABLE_MARKERS missing "data not available".
     _normalize_moa_support_text("Data not available") must be in the marker
     set so Drug Profile rows using that placeholder do not trigger
     UNSUPPORTED_MOA_CLAIM.
"""

import json
from pathlib import Path

import pytest

import src.agents.drug_target.tools.stage_logic as stage_logic
from src.agents.drug_target.tools.stage_logic import (
    _MOA_UNAVAILABLE_MARKERS,
    _normalize_moa_support_text,
    validate_drug_md,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_drug_md(tmp_path: Path, body: str) -> Path:
    """Write a minimal drug.md with the given body text and return data_dir."""
    (tmp_path / "drug.md").write_text(body, encoding="utf-8")
    return tmp_path


def _issues_of_type(drug_text: str, tmp_path: Path, issue_type: str) -> list[dict]:
    """Run validate_drug_md (Path overload) and return issues of the given type.

    validate_drug_md is decorated with @tool and becomes a StructuredTool.
    Unwrap to the underlying function the same way test_finalization_validator
    does (line 681: ``getattr(validate_drug_md, "func", None) or validate_drug_md``).
    """
    _minimal_drug_md(tmp_path, drug_text)
    impl = getattr(validate_drug_md, "func", None) or validate_drug_md
    result = json.loads(impl(tmp_path))
    return [i for i in result.get("issues", []) if i.get("type") == issue_type]


# ---------------------------------------------------------------------------
# F-A: DECIMAL_RUBRIC_SCORES
# ---------------------------------------------------------------------------


class TestDecimalRubricScoresRegex:
    """Verify the DECIMAL_RUBRIC_SCORES regex distinguishes PPI confidence
    scores (false positive) from actual rubric decimal scores (true positive).
    """

    def test_string_ppi_confidence_score_does_not_trigger(self, tmp_path: Path) -> None:
        """F-A regression: drug.md fragment from res_ipf_openai2 trace (line 373).

        'the STRING combined score 0.999 predicts that perturbing ICAM1 or ITGB2'
        is a PPI database confidence value, NOT a rubric score.  The validator
        must NOT raise DECIMAL_RUBRIC_SCORES for this text.
        """
        drug_text = (
            "## ICAM1 Evidence\n\n"
            "Network analysis shows that the STRING combined score 0.999 "
            "predicts that perturbing ICAM1 or ITGB2 would affect downstream "
            "inflammatory signalling.\n"
        )
        issues = _issues_of_type(drug_text, tmp_path, "DECIMAL_RUBRIC_SCORES")
        assert issues == [], (
            "STRING PPI confidence score 'combined score 0.999' was falsely "
            "flagged as DECIMAL_RUBRIC_SCORES; the regex must not match "
            "bare 'combined score <decimal>' phrases."
        )

    def test_actual_decimal_rubric_score_is_flagged(self, tmp_path: Path) -> None:
        """F-A preserve: a genuine decimal rubric score MUST still be flagged.

        Rubric matrix values like 'combined_total: 5.5' represent a fractional
        integer in the druggability_matrix and are always invalid (should be int).
        """
        drug_text = (
            "## Druggability Matrix\n\n"
            "combined_total: 5.5\n"
            "validated_total: 3\n"
            "exploratory_track: 2\n"
        )
        issues = _issues_of_type(drug_text, tmp_path, "DECIMAL_RUBRIC_SCORES")
        assert len(issues) >= 1, (
            "A genuine decimal rubric score 'combined_total: 5.5' was not "
            "flagged by DECIMAL_RUBRIC_SCORES; the check must still catch "
            "fractional values in underscore-delimited rubric field names."
        )


# ---------------------------------------------------------------------------
# F-B: _MOA_UNAVAILABLE_MARKERS missing "data not available"
# ---------------------------------------------------------------------------


class TestMoaUnavailableMarkers:
    """Verify that 'Data not available' is treated as an explicit placeholder
    and does not generate UNSUPPORTED_MOA_CLAIM issues.
    """

    def test_normalized_data_not_available_is_in_marker_set(self) -> None:
        """F-B unit: casefold('Data not available') must be in _MOA_UNAVAILABLE_MARKERS.

        The validator calls _normalize_moa_support_text which casefoldsthe value,
        then checks membership in _MOA_UNAVAILABLE_MARKERS.  If 'data not available'
        is absent, the next branch looks it up as a drug name and generates a
        false UNSUPPORTED_MOA_CLAIM.
        """
        normalized = _normalize_moa_support_text("Data not available")
        assert normalized in _MOA_UNAVAILABLE_MARKERS, (
            f"'{normalized}' is not in _MOA_UNAVAILABLE_MARKERS; "
            "add 'data not available' to the frozenset."
        )

    def test_data_not_available_moa_cell_does_not_raise_unsupported_moa(
        self, tmp_path: Path
    ) -> None:
        """F-B integration: Drug Profile row with 'Data not available' MoA cell.

        Mirrors drug.md:233 ITGB2 Clinical Compounds row from the trace.
        With an empty data_dir (no resolved_drugs.json, no stage3 files) every
        real drug name would trigger UNSUPPORTED_MOA_CLAIM, so only the
        placeholder row should be exempt.
        """
        # Minimal Drug Profile table with 'Data not available' as MoA cell.
        # The table must have enough columns to satisfy _iter_drug_profile_moa_cells.
        drug_text = (
            "## Drug Profiles\n\n"
            "### ITGB2\n\n"
            "#### Clinical Compounds\n\n"
            "| Drug Name | ChEMBL ID | Mechanism of Action | "
            "Approval Status | Notes |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| Efalizumab | CHEMBL1201572 | Data not available | "
            "Withdrawn | Withdrawn 2009 |\n"
        )
        # data_dir with only drug.md — no MoA support files
        _minimal_drug_md(tmp_path, drug_text)

        issues = stage_logic._check_unsupported_moa_claim(drug_text, tmp_path)
        unsupported = [i for i in issues if i.get("code") == "UNSUPPORTED_MOA_CLAIM"]
        assert unsupported == [], (
            "UNSUPPORTED_MOA_CLAIM was raised for 'Data not available' MoA cell; "
            "this placeholder must be in _MOA_UNAVAILABLE_MARKERS."
        )
