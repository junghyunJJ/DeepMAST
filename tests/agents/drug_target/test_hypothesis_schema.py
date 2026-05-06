from __future__ import annotations

import json
from pathlib import Path

from src.agents.drug_target.tools import save_evidence, save_hypothesis_report


def _write_hypothesis_evidence(tmp_path: Path) -> Path:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "CD4"}]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_filter_results.json").write_text(
        json.dumps([
            {"ligand": "HLA-DPA1", "receptor": "CD4", "passed": False},
            {"ligand": "FN1", "receptor": "CD4", "passed": True},
        ]),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_HLA-DPA1--CD4.json").write_text("{}", encoding="utf-8")
    (evidence_dir / "stage1_FN1--CD4.json").write_text("{}", encoding="utf-8")
    (evidence_dir / "stage3_CD4.json").write_text("{}", encoding="utf-8")
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
                    "stage1_HLA-DPA1--CD4.json_FAILED",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["cd4"],
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
            "orphan_files": ["stage1_FN1--CD4.json_FAILED"],
        },
    }


def test_save_hypothesis_report_canonicalizes_labels_and_failed_refs(tmp_path: Path) -> None:
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
    assert hyp["biological_entities"]["genes"] == ["CD4"]
    assert hyp["evidence_reference_details"][1] == {
        "filename": "stage1_HLA-DPA1--CD4.json",
        "usage": "contrast",
        "stage1_pair_status": "failed",
        "display_reference": "stage1_HLA-DPA1--CD4.json_FAILED",
    }
    assert saved["gap_analysis"]["orphan_files"] == ["stage1_FN1--CD4.json"]


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
                "biological_entities": {"genes": ["cd4"]},
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

