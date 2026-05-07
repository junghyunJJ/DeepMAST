from __future__ import annotations

from src.agents.drug_target.evidence_filenames import EvidenceFiles


def test_evidence_file_registry_returns_canonical_paths() -> None:
    assert EvidenceFiles.assessment_results() == "evidence/assessment_results.json"
    assert EvidenceFiles.hypothesis_report() == "evidence/hypothesis_report.json"
    assert EvidenceFiles.stage2_evidence() == "evidence/stage2_evidence.json"
    assert EvidenceFiles.stage1_filter_results() == "evidence/stage1_filter_results.json"
    assert EvidenceFiles.stage3_gene("cd4") == "evidence/stage3_CD4.json"
    assert EvidenceFiles.opentargets_gene("cd4") == "evidence/ot_CD4.json"


def test_evidence_file_registry_diagnoses_stale_names() -> None:
    diag = EvidenceFiles.diagnose("target_assessment.json")
    assert diag == {
        "valid": False,
        "code": "FILENAME_REGISTRY_DRIFT",
        "replacement": "evidence/assessment_results.json",
    }
    assert EvidenceFiles.diagnose("evidence/assessment_results.json")["valid"] is True

