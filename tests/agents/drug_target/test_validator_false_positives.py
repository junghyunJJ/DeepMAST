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


def _findings_of_type(drug_text: str, tmp_path: Path, issue_type: str) -> list[dict]:
    _minimal_drug_md(tmp_path, drug_text)
    impl = getattr(validate_drug_md, "func", None) or validate_drug_md
    result = json.loads(impl(tmp_path))
    return [i for i in result.get("findings", []) if i.get("type") == issue_type]


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


# ---------------------------------------------------------------------------
# F-C: PRECLINICAL_CALLED_APPROVED line crossing / duplicate names
# ---------------------------------------------------------------------------


class TestPreclinicalCalledApprovedFalsePositives:
    """Preclinical status checks must stay scoped to the cited drug claim."""

    def test_preclinical_check_does_not_cross_into_next_line_phase_claim(
        self, tmp_path: Path
    ) -> None:
        """A preclinical bullet followed by an unrelated Phase 4 line is valid.

        The live res_ipf_openai run exposed a regex over-match where the
        preclinical drug name matched on one bullet, then ``Phase 4`` from the
        next clinical bullet was consumed through DOTALL matching.
        """
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "resolved_drugs.json").write_text(
            json.dumps(
                [
                    {
                        "resolved_name": "Example Preclinical Compound",
                        "source": "chembl",
                        "max_phase": None,
                    }
                ]
            ),
            encoding="utf-8",
        )
        drug_text = (
            "- **Example Preclinical Compound** (ChEMBL: CHEMBL1) — "
            "mechanism not available, Max Phase: Preclinical\n"
            "- **Example Clinical Compound** (ChEMBL: CHEMBL2) — "
            "mechanism not available, Phase 4 clinical evidence\n"
        )

        issues = _issues_of_type(
            drug_text, tmp_path, "PRECLINICAL_CALLED_APPROVED"
        )

        assert issues == []

    def test_preclinical_duplicate_name_with_clinical_source_is_not_flagged(
        self, tmp_path: Path
    ) -> None:
        """Clinical evidence for the same name overrides a ChEMBL preclinical duplicate."""
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "resolved_drugs.json").write_text(
            json.dumps(
                [
                    {
                        "resolved_name": "LIFITEGRAST",
                        "source": "chembl",
                        "max_phase": None,
                    },
                    {
                        "resolved_name": "LIFITEGRAST",
                        "source": "opentargets",
                        "max_phase": 4,
                    },
                ]
            ),
            encoding="utf-8",
        )
        drug_text = (
            "- **LIFITEGRAST** (ChEMBL: CHEMBL3137314) — "
            "mechanism not available, Phase 4 clinical evidence\n"
        )

        issues = _issues_of_type(
            drug_text, tmp_path, "PRECLINICAL_CALLED_APPROVED"
        )

        assert issues == []

    def test_preclinical_same_line_approved_claim_still_fires(
        self, tmp_path: Path
    ) -> None:
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "resolved_drugs.json").write_text(
            json.dumps(
                [
                    {
                        "resolved_name": "Example Preclinical Compound",
                        "source": "chembl",
                        "max_phase": None,
                    }
                ]
            ),
            encoding="utf-8",
        )
        drug_text = "Example Preclinical Compound is FDA approved for IPF.\n"

        issues = _issues_of_type(
            drug_text, tmp_path, "PRECLINICAL_CALLED_APPROVED"
        )

        assert len(issues) == 1


class TestMultiFieldSourceAnnotations:
    def test_multifield_source_annotation_counts_as_anchored(
        self, tmp_path: Path
    ) -> None:
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "annotation_fields.json").write_text(
            json.dumps({"classification": "validated_target", "priority": "high"}),
            encoding="utf-8",
        )
        drug_text = (
            "MUC1 and FN1 remain high-priority candidates. "
            "[source: classification, priority]\n"
        )

        issues = _findings_of_type(drug_text, tmp_path, "UNANCHORED_SENTENCE")

        assert issues == []

    def test_source_database_terms_and_sentence_starters_are_not_drugs(
        self, tmp_path: Path
    ) -> None:
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "annotation_fields.json").write_text(
            json.dumps(
                {
                    "stage1_filter_results": [],
                    "kegg_pathways": [],
                    "reactome_pathways": [],
                    "clinical_drugs": [],
                }
            ),
            encoding="utf-8",
        )
        drug_text = (
            "The passed pairs are characterized by strong STRING support. "
            "[source: stage1_filter_results]\n"
            "The absence of listed KEGG or Reactome pathway annotations is "
            "reported in the source data. [source: kegg_pathways, reactome_pathways]\n"
            "Because MUC1 already has multiple clinical-stage agents listed, "
            "the profile is tractable. [source: clinical_drugs]\n"
        )

        fabricated = _findings_of_type(drug_text, tmp_path, "FABRICATED_DRUG_NAME")

        assert fabricated == []

    def test_common_sentence_initial_words_not_flagged_as_drugs(
        self,
        tmp_path: Path,
    ) -> None:
        drug_text = (
            "Pairs that pass the filter provide a stronger foundation for target selection. "
            "[source: stage1_filter_results]\n"
            "Approved indications should be stated exactly as provided and not extended to IPF. "
            "[source: clinical_drugs]\n"
            "Any summary of CD4 drugs should stay strictly within the source-listed products. "
            "[source: clinical_drugs]\n"
            "That context supports mechanistic relevance without implying direct efficacy. "
            "[source: stage1_filter_results]\n"
            "Next steps should prioritize closing evidence gaps around the top candidates. "
            "[source: stage3_candidates]\n"
            "Six stage3 candidates were retained across the top combined_total scores. "
            "[source: stage3_candidates]\n"
            "MUC1 is linked to NF-kappa-B, ERK/SRC signaling, and adhesion programs. "
            "[source: stage1_filter_results]\n"
            "MUC1 is linked to Ras/MAPK pathway modulation in the source context. "
            "[source: stage1_filter_results]\n"
            "CD4 is contextualized by MHC class II antigen presentation. "
            "[source: stage1_filter_results]\n"
            "Therapeutically, this favors perturbation experiments over efficacy claims. "
            "[source: hypothesis_data]\n"
            "Lower-scoring genes remain useful as background context. "
            "[source: combined_total]\n"
            "Where evidence is incomplete, the recommendation is continued validation. "
            "[source: clinical_drugs]\n"
            "When Stage 1 validation is present, the pair is spatially compatible. "
            "[source: stage1_filter_results]\n"
            "Approval year details should be omitted unless the source supplies them. "
            "[source: clinical_drugs]\n"
        )

        fabricated = _findings_of_type(drug_text, tmp_path, "FABRICATED_DRUG_NAME")
        false_words = {
            "Pairs",
            "Approved",
            "Any",
            "That",
            "Next",
            "Six",
            "SRC",
            "Ras",
            "MHC",
            "Therapeutically",
            "Lower",
            "Where",
            "When",
            "Approval",
        }
        false_hits = [
            finding
            for finding in fabricated
            if any(word in finding.get("actual", "") for word in false_words)
        ]

        assert false_hits == []
