from __future__ import annotations

import json
from pathlib import Path

from src.agents.drug_target.tools import (
    save_evidence,
    save_hypothesis_report,
    validate_evidence_references,
)


def _write_hypothesis_evidence(tmp_path: Path) -> Path:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "CD4"}, {"gene": "FN1"}]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_filter_results.json").write_text(
        json.dumps([
            {"ligand": "HLA-DPA1", "receptor": "CD4", "passed": False},
            {"ligand": "FN1", "receptor": "CD4", "passed": True},
            {"ligand": "FN1", "receptor": "PLAUR", "passed": False},
            {"ligand": "FN1", "receptor": "SDC2", "passed": True},
        ]),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_HLA-DPA1--CD4.json").write_text("{}", encoding="utf-8")
    (evidence_dir / "stage1_FN1--CD4.json").write_text("{}", encoding="utf-8")
    (evidence_dir / "stage1_FN1--PLAUR.json").write_text("{}", encoding="utf-8")
    (evidence_dir / "stage1_FN1--SDC2.json").write_text("{}", encoding="utf-8")
    (evidence_dir / "stage3_CD4.json").write_text("{}", encoding="utf-8")
    (evidence_dir / "stage3_FN1.json").write_text("{}", encoding="utf-8")
    return tmp_path


def _strict_report() -> dict:
    return {
        "schema_version": "hypothesis_report.v2",
        "disease": "IPF",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "[FEATURED-GAP] CD4 contrast hypothesis",
                "category": "Mechanism of Action",
                "core_claim": "CD4 biology is testable.",
                "evidence_references": [
                    "stage3_CD4.json",
                    "stage1_FN1--CD4.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["cd4", "fn1"],
                    "pathways": [],
                    "cell_types": [],
                    "drugs": [],
                },
                "falsifiable_prediction": "Qualitative cytokine response change.",
                "validation_approach": "Assay CD4 perturbation.",
                "scores": {
                    "evidence_coverage": 1.0,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.75,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 3,
            "referenced_files": 2,
            "orphan_files": ["stage1_FN1--CD4.json"],
        },
    }


def _clone_report() -> dict:
    return json.loads(json.dumps(_strict_report()))


def test_save_hypothesis_report_canonicalizes_labels_and_refs(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)

    result = json.loads(
        save_hypothesis_report.invoke(
            {"data_dir": str(data_dir), "report": _strict_report()}
        )
    )

    assert result["saved"] is True, result
    saved = json.loads((data_dir / "evidence" / "hypothesis_report.json").read_text())
    hyp = saved["hypotheses"][0]
    assert saved["schema_version"] == "hypothesis_report.v2"
    assert hyp["title"] == "CD4 contrast hypothesis"
    assert hyp["gap_type"] == "featured_coverage"
    assert hyp["biological_entities"]["genes"] == ["CD4", "FN1"]
    assert hyp["evidence_reference_details"][1] == {
        "filename": "stage1_FN1--CD4.json",
        "usage": "primary",
        "stage1_pair_status": "passed",
        "display_reference": "stage1_FN1--CD4.json",
    }
    assert saved["gap_analysis"] == {
        "total_evidence_files": 4,
        "referenced_files": 2,
        "orphan_files": ["stage1_FN1--SDC2.json", "stage3_FN1.json"],
    }
    assert saved["evidence_coverage_pct"] == 50.0


def test_save_hypothesis_report_recomputes_gap_analysis_from_actual_citations(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _clone_report()
    report["gap_analysis"] = {
        "total_evidence_files": 99,
        "referenced_files": 1,
        "orphan_files": [
            "stage1_FN1--CD4.json",
            "stage3_CD4.json",
            "stage3_NOT_REAL.json",
        ],
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result
    saved = json.loads((data_dir / "evidence" / "hypothesis_report.json").read_text())
    assert saved["gap_analysis"] == {
        "total_evidence_files": 4,
        "referenced_files": 2,
        "orphan_files": ["stage1_FN1--SDC2.json", "stage3_FN1.json"],
    }
    cited = {
        ref
        for hyp in saved["hypotheses"]
        for ref in hyp.get("evidence_references", [])
    }
    assert not (set(saved["gap_analysis"]["orphan_files"]) & cited)
    assert saved["evidence_coverage_pct"] == 50.0


def test_save_hypothesis_report_rejects_failed_pair_semantic_claim_without_citation(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _clone_report()
    hyp = report["hypotheses"][0]
    hyp["title"] = "FN1-PLAUR axis drives fibrotic remodeling"
    hyp["core_claim"] = (
        "The FN1-PLAUR interaction is proposed as the primary mechanism, "
        "but this pair failed Stage 1."
    )
    hyp["evidence_references"] = ["stage3_FN1.json", "stage3_CD4.json"]
    hyp["biological_entities"]["genes"] = ["FN1", "PLAUR", "CD4"]

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is False
    assert any("FN1--PLAUR" in v for v in result.get("failed_pair_violations", []))
    assert not (data_dir / "evidence" / "hypothesis_report.json").exists()


def test_save_hypothesis_report_accepts_passed_pair_claim(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _clone_report()
    hyp = report["hypotheses"][0]
    hyp["title"] = "FN1-SDC2 axis supports matrix remodeling"
    hyp["core_claim"] = "The passed FN1-SDC2 pair supports a testable matrix-remodeling mechanism."
    hyp["evidence_references"] = [
        "stage3_FN1.json",
        "stage3_CD4.json",
        "stage1_FN1--SDC2.json",
    ]
    hyp["biological_entities"]["genes"] = ["FN1", "SDC2", "CD4"]

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result


def test_save_hypothesis_report_accepts_passed_pair_with_failed_pair_member_context(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _clone_report()
    hyp = report["hypotheses"][0]
    hyp["title"] = "FN1-SDC2 axis supports matrix remodeling"
    hyp["core_claim"] = (
        "The passed FN1-SDC2 pair supports a testable matrix-remodeling mechanism. "
        "PLAUR is tracked only as separate gene-level context, not as an L-R axis."
    )
    hyp["evidence_references"] = [
        "stage3_FN1.json",
        "stage3_CD4.json",
        "stage1_FN1--SDC2.json",
    ]
    hyp["biological_entities"]["genes"] = ["FN1", "SDC2", "PLAUR", "CD4"]

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result


def test_save_hypothesis_report_allows_gene_level_member_of_failed_pair(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _clone_report()
    hyp = report["hypotheses"][0]
    hyp["title"] = "FN1 matrix remodeling hypothesis"
    hyp["core_claim"] = "FN1 Stage 3 evidence supports a gene-level remodeling hypothesis."
    hyp["evidence_references"] = ["stage3_FN1.json", "stage3_CD4.json"]
    hyp["biological_entities"]["genes"] = ["FN1", "CD4"]

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result


def test_save_hypothesis_report_allows_both_failed_pair_genes_without_pair_claim(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _clone_report()
    hyp = report["hypotheses"][0]
    hyp["title"] = "FN1 remodeling with PLAUR context"
    hyp["core_claim"] = (
        "FN1 and PLAUR are listed as separate extracellular remodeling markers. "
        "The retained mechanism is grounded in FN1 Stage 3 evidence."
    )
    hyp["evidence_references"] = ["stage3_FN1.json", "stage3_CD4.json"]
    hyp["biological_entities"]["genes"] = ["FN1", "PLAUR", "CD4"]

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result


def test_save_hypothesis_report_rejects_failed_pair_reference_with_suffix(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _clone_report()
    hyp = report["hypotheses"][0]
    hyp["evidence_references"] = [
        "stage3_FN1.json",
        "stage3_CD4.json",
        "stage1_FN1--PLAUR.json_FAILED",
    ]

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is False
    assert any("_FAILED" in err or "failed Stage 1 pair" in err for err in result["errors"])


def test_save_hypothesis_report_rejects_stage1_reference_without_filter_results(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    (data_dir / "evidence" / "stage1_filter_results.json").unlink()
    report = _clone_report()

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is False
    assert any("without proven passed=true" in err for err in result["errors"])


def test_validate_evidence_references_rejects_stage1_reference_without_filter_results(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    (data_dir / "evidence" / "stage1_filter_results.json").write_text("{not-json")

    result = json.loads(
        validate_evidence_references.invoke(
            {
                "data_dir": str(data_dir),
                "references": ["stage1_FN1--CD4.json", "stage3_CD4.json"],
            }
        )
    )

    assert result["valid"] is False
    assert "stage1_FN1--CD4.json" in result["invalid_references"]
    assert any("not proven passed=true" in item["reason"] for item in result["denied_citations"])


def test_save_hypothesis_report_rejects_missing_strict_scores(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _strict_report()
    del report["hypotheses"][0]["scores"]["composite"]

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is False
    assert any("scores.composite" in err for err in result["errors"])
    assert not (data_dir / "evidence" / "hypothesis_report.json").exists()


def test_save_evidence_legacy_wrapper_writes_v2_projection(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    legacy = {
        "disease": "IPF",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "[GAP] CD4 legacy hypothesis",
                "category": "MoA",
                "core_claim": "CD4 is testable.",
                "evidence_references": ["stage3_CD4.json"],
                "biological_entities": {"genes": ["cd4", "fn1"]},
                "falsifiable_prediction": "Qualitative response.",
                "validation_approach": "Assay.",
            }
        ],
        "gap_analysis": {"orphan_files": []},
    }

    result = json.loads(
        save_evidence.invoke(
            {
                "data_dir": str(data_dir),
                "filename": "hypothesis_report.json",
                "data": legacy,
            }
        )
    )

    assert result["saved"] is True, result
    saved = json.loads((data_dir / "evidence" / "hypothesis_report.json").read_text())
    hyp = saved["hypotheses"][0]
    assert saved["schema_version"] == "hypothesis_report.v2"
    assert hyp["category"] == "Mechanism of Action"
    assert hyp["gap_type"] == "orphan_evidence"
    assert hyp["title"] == "CD4 legacy hypothesis"
    assert hyp["evidence_references"] == [
        detail["display_reference"] for detail in hyp["evidence_reference_details"]
    ]


def test_save_hypothesis_report_keeps_contrast_details_out_of_primary_refs(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _clone_report()
    hyp = report["hypotheses"][0]
    hyp["evidence_references"] = ["stage3_FN1.json", "stage3_CD4.json"]
    hyp["evidence_reference_details"] = [
        {"filename": "stage3_FN1.json", "usage": "primary"},
        {"filename": "stage3_CD4.json", "usage": "supporting"},
        {"filename": "stage1_FN1--PLAUR.json", "usage": "contrast"},
    ]
    hyp["negative_contrast_context"] = (
        "stage1_FN1--PLAUR.json failed Stage 1 and is retained only as "
        "negative contrast metadata."
    )
    hyp["biological_entities"]["genes"] = ["FN1", "CD4"]

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result
    saved = json.loads((data_dir / "evidence" / "hypothesis_report.json").read_text())
    saved_hyp = saved["hypotheses"][0]
    assert saved_hyp["evidence_references"] == ["stage3_FN1.json", "stage3_CD4.json"]
    assert saved_hyp["contrast_references"] == ["stage1_FN1--PLAUR.json"]
    contrast_detail = saved_hyp["evidence_reference_details"][2]
    assert contrast_detail == {
        "filename": "stage1_FN1--PLAUR.json",
        "usage": "contrast",
        "stage1_pair_status": "failed",
        "display_reference": "stage1_FN1--PLAUR.json",
    }
    assert "_FAILED" not in json.dumps(saved_hyp)
