"""Tests for compute_drug_evidence_scores() and related helpers."""

import pytest
from src.agents.drug_target.tools.stage_logic import (
    compute_drug_evidence_scores,
    _check_opentargets_approved,
    _indication_matches_disease,
    _indication_is_oncology,
)


# ---------------------------------------------------------------------------
# _indication_matches_disease
# ---------------------------------------------------------------------------

class TestIndicationMatchesDisease:
    def test_direct_match(self):
        assert _indication_matches_disease("breast cancer", "breast cancer")

    def test_partial_match(self):
        assert _indication_matches_disease("HER2-positive breast cancer", "breast cancer")

    def test_no_match(self):
        assert not _indication_matches_disease("hepatocellular carcinoma", "breast cancer")

    def test_breast_keyword_variants(self):
        assert _indication_matches_disease("triple negative breast cancer", "breast cancer")
        assert _indication_matches_disease("mammary carcinoma", "breast cancer")
        assert _indication_matches_disease("TNBC", "breast cancer")

    def test_non_breast_disease(self):
        assert _indication_matches_disease("renal cell carcinoma", "renal cell carcinoma")
        assert not _indication_matches_disease("breast cancer", "renal cell carcinoma")


# ---------------------------------------------------------------------------
# _indication_is_oncology
# ---------------------------------------------------------------------------

class TestIndicationIsOncology:
    def test_cancer(self):
        assert _indication_is_oncology("hepatocellular carcinoma")
        assert _indication_is_oncology("breast cancer")

    def test_non_cancer(self):
        assert not _indication_is_oncology("rheumatoid arthritis")
        assert not _indication_is_oncology("diabetes mellitus")


# ---------------------------------------------------------------------------
# _check_opentargets_approved
# ---------------------------------------------------------------------------

class TestCheckOpentargetsApproved:
    def test_none(self):
        assert not _check_opentargets_approved(None)

    def test_empty(self):
        assert not _check_opentargets_approved([])

    def test_approved(self):
        data = [{"modality": "SM", "top_category": "Approved Drug", "value": True}]
        assert _check_opentargets_approved(data)

    def test_not_approved(self):
        data = [{"modality": "SM", "top_category": "Clinical Candidate", "value": True}]
        assert not _check_opentargets_approved(data)

    def test_has_drug_field(self):
        data = [{"approved_drug": True}]
        assert _check_opentargets_approved(data)


# ---------------------------------------------------------------------------
# compute_drug_evidence_scores
# ---------------------------------------------------------------------------

class TestComputeDrugEvidenceScores:
    """Test scoring logic with realistic scenarios."""

    def test_kdr_sorafenib_other_cancer_approved(self):
        """KDR: Sorafenib approved for hepatocellular/renal carcinoma, NOT breast cancer.
        Expected: existing_drug_evidence >= 1 (repurposing candidate).
        """
        drugs = [
            {
                "chembl_id": "CHEMBL1336",
                "drug_name": "SORAFENIB",
                "target_gene": "KDR",
                "mechanism_of_action": "VEGFR2 inhibitor",
                "indications": [
                    {"efo_term": "hepatocellular carcinoma", "max_phase": 4.0},
                    {"efo_term": "renal cell carcinoma", "max_phase": 4.0},
                    {"efo_term": "thyroid gland carcinoma", "max_phase": 4.0},
                ],
            }
        ]
        result = compute_drug_evidence_scores(drugs, "breast cancer")
        assert result["existing_drug_evidence"] >= 1, (
            f"KDR should have existing_drug_evidence >= 1, got {result['existing_drug_evidence']}"
        )
        # Sorafenib is Phase 4 in other cancers -> clinical_trial_activity >= 1
        assert result["clinical_trial_activity"] >= 1

    def test_kdr_with_opentargets_approved(self):
        """KDR with OpenTargets SM Approved Drug = True."""
        drugs = [
            {
                "chembl_id": "CHEMBL1336",
                "drug_name": "SORAFENIB",
                "target_gene": "KDR",
                "indications": [
                    {"efo_term": "hepatocellular carcinoma", "max_phase": 4.0},
                ],
            }
        ]
        ot = [{"modality": "SM", "top_category": "Approved Drug", "value": True}]
        result = compute_drug_evidence_scores(drugs, "breast cancer", ot)
        assert result["existing_drug_evidence"] >= 1

    def test_flt1_other_indications(self):
        """FLT1: drugs exist but for other indications.
        Expected: existing_drug_evidence >= 1.
        """
        drugs = [
            {
                "chembl_id": "CHEMBL_FLT1_DRUG",
                "drug_name": "BEVACIZUMAB",
                "target_gene": "FLT1",
                "indications": [
                    {"efo_term": "colorectal cancer", "max_phase": 4.0},
                    {"efo_term": "non-small cell lung cancer", "max_phase": 4.0},
                ],
            }
        ]
        result = compute_drug_evidence_scores(drugs, "breast cancer")
        assert result["existing_drug_evidence"] >= 1

    def test_tnfsf10_no_approved_drug(self):
        """TNFSF10: research compounds only, no approved drugs.
        Expected: existing_drug_evidence = 0.
        """
        drugs = [
            {
                "chembl_id": "CHEMBL_TNFSF10",
                "drug_name": "RESEARCH_COMPOUND_1",
                "target_gene": "TNFSF10",
                "indications": [],  # no indications
            }
        ]
        result = compute_drug_evidence_scores(drugs, "breast cancer")
        assert result["existing_drug_evidence"] == 0

    def test_agrn_no_drugs(self):
        """AGRN: no drugs at all.
        Expected: existing_drug_evidence = 0.
        """
        result = compute_drug_evidence_scores([], "breast cancer")
        assert result["existing_drug_evidence"] == 0
        assert result["clinical_trial_activity"] == 0

    def test_dag1_no_drugs(self):
        """DAG1: no drugs at all.
        Expected: existing_drug_evidence = 0.
        """
        result = compute_drug_evidence_scores([], "breast cancer")
        assert result["existing_drug_evidence"] == 0

    def test_disease_phase3_gets_score3(self):
        """Drug with Phase 3+ for target disease -> existing_drug_evidence = 3."""
        drugs = [
            {
                "chembl_id": "CHEMBL_TEST",
                "drug_name": "TEST_DRUG",
                "target_gene": "TEST",
                "indications": [
                    {"efo_term": "breast cancer", "max_phase": 3.0},
                ],
            }
        ]
        result = compute_drug_evidence_scores(drugs, "breast cancer")
        assert result["existing_drug_evidence"] == 3

    def test_disease_phase2_gets_score2(self):
        """Drug with Phase 2 for target disease -> existing_drug_evidence = 2."""
        drugs = [
            {
                "chembl_id": "CHEMBL_TEST",
                "drug_name": "TEST_DRUG",
                "target_gene": "TEST",
                "indications": [
                    {"efo_term": "breast cancer", "max_phase": 2.0},
                ],
            }
        ]
        result = compute_drug_evidence_scores(drugs, "breast cancer")
        assert result["existing_drug_evidence"] == 2

    def test_only_opentargets_approved_no_chembl(self):
        """No ChEMBL drugs but OpenTargets says approved -> score 1."""
        ot = [{"modality": "SM", "top_category": "Approved Drug", "value": True}]
        result = compute_drug_evidence_scores([], "breast cancer", ot)
        assert result["existing_drug_evidence"] == 1

    def test_detail_structure(self):
        """Verify detail dict contains expected keys."""
        result = compute_drug_evidence_scores([], "breast cancer")
        detail = result["detail"]
        assert "disease_phase_max" in detail
        assert "other_phase_max" in detail
        assert "disease_indication_count" in detail
        assert "other_indication_count" in detail
        assert "opentargets_approved_drug" in detail
        assert "matched_disease_drugs" in detail
        assert "matched_other_drugs" in detail


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
