from __future__ import annotations

import json
from pathlib import Path

from src.agents.drug_target.subagents import prompts
from src.agents.drug_target.tools import save_hypothesis_report
from src.agents.drug_target.tools.evidence_loader import (
    load_evidence_files,
    validate_evidence_references,
)
from src.agents.drug_target.tools.hypothesis_grounding import (
    validate_hypothesis_grounding,
)
from src.agents.drug_target.tools.hypothesis_schema import (
    validate_hypothesis_report_quality,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_hypothesis_context(evidence: Path, featured: list[str]) -> None:
    _write_json(
        evidence / "assessment_results.json",
        {"stage3_candidates": [{"gene": gene} for gene in featured]},
    )
    _write_json(evidence / "gene_manifest.json", {"genes": featured})
    _write_json(evidence / "known_drugs.json", {"disease": "pulmonary fibrosis"})
    _write_json(
        evidence / "celltype_resolution.json",
        {
            "interest_celltypes": ["AT2", "Transitional AT2"],
            "primary_resolved_celltype": "pulmonary alveolar type 2 cell",
            "matches": [
                {
                    "input_celltype": "AT2",
                    "matched_celltype": "pulmonary alveolar type 2 cell",
                    "match_mode": "alias",
                    "lost_modifiers": [],
                },
                {
                    "input_celltype": "Transitional AT2",
                    "matched_celltype": "pulmonary alveolar type 2 cell",
                    "match_mode": "state_stripped_alias",
                    "lost_modifiers": ["transitional"],
                },
            ],
        },
    )
    for gene in featured:
        _write_json(evidence / f"stage3_{gene}.json", {"gene": gene})


def _stage1_payload(
    ligand: str,
    receptor: str,
    *,
    passed: bool = True,
    gene_a_diff: float = 0.2,
    gene_b_diff: float = 0.2,
    coexpr_diff: float = 0.2,
    target_cell_type: str = "pulmonary alveolar type 2 cell",
) -> dict:
    return {
        "ligand": ligand,
        "receptor": receptor,
        "string_ppi": {
            "gene_a": ligand,
            "gene_b": receptor,
            "executed": True,
            "interaction_found": True,
            "string_record_found": True,
            "max_combined_score": 0.95 if passed else 0.60,
            "errors": [],
        },
        "census_validation": {
            "disease": "pulmonary fibrosis",
            "requested_cell_type": target_cell_type,
            "resolved_cell_type": target_cell_type,
            "resolution_mode": "exact",
            "target_vs_rest": {
                "gene_a": {
                    "diff": gene_a_diff,
                    "p_value": 0.0,
                    "target_pct": 0.5,
                    "rest_pct": 0.3,
                },
                "gene_b": {
                    "diff": gene_b_diff,
                    "p_value": 0.0,
                    "target_pct": 0.5,
                    "rest_pct": 0.3,
                },
                "coexpression": {
                    "diff": coexpr_diff,
                    "p_value": 0.0,
                    "target_pct": 0.25,
                    "rest_pct": 0.05,
                },
            },
            "executed": True,
            "source": "csv_integration",
            "csv_file": (
                f"census_{ligand.lower()}_{receptor.lower()}_"
                "pulmonary_alveolar_type_2_cell.csv"
            ),
        },
        "stage1_filter": {
            "passed": passed,
            "string_combined": 0.95 if passed else 0.60,
            "string_status": "in_db",
            "census_coexpr_pvalue": 0.0,
            "census_gene_a_pvalue": 0.0,
            "census_gene_b_pvalue": 0.0,
        },
    }


def _write_stage1_pair(
    evidence: Path,
    ligand: str,
    receptor: str,
    *,
    passed: bool = True,
    gene_a_diff: float = 0.2,
    gene_b_diff: float = 0.2,
    coexpr_diff: float = 0.2,
) -> None:
    _write_json(
        evidence / f"stage1_{ligand}--{receptor}.json",
        _stage1_payload(
            ligand,
            receptor,
            passed=passed,
            gene_a_diff=gene_a_diff,
            gene_b_diff=gene_b_diff,
            coexpr_diff=coexpr_diff,
        ),
    )


def _write_stage1_filter_results(
    evidence: Path,
    rows: list[tuple[str, str, bool]],
) -> None:
    _write_json(
        evidence / "stage1_filter_results.json",
        [
            {
                "ligand": ligand,
                "receptor": receptor,
                "passed": passed,
            }
            for ligand, receptor, passed in rows
        ],
    )


def test_hypothesis_scope_loads_celltype_resolution_json(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _write_json(
        evidence / "assessment_results.json",
        {"stage3_candidates": [{"gene": "FN1"}]},
    )
    _write_json(evidence / "gene_manifest.json", {"genes": ["FN1"]})
    _write_json(evidence / "known_drugs.json", {"disease": "pulmonary fibrosis"})
    _write_json(evidence / "stage1_filter_results.json", [])
    _write_json(
        evidence / "celltype_resolution.json",
        {
            "interest_celltypes": ["AT2", "Transitional AT2"],
            "primary_resolved_celltype": "pulmonary alveolar type 2 cell",
            "matches": [
                {
                    "input_celltype": "AT2",
                    "matched_celltype": "pulmonary alveolar type 2 cell",
                    "match_mode": "alias",
                    "lost_modifiers": [],
                },
                {
                    "input_celltype": "Transitional AT2",
                    "matched_celltype": "pulmonary alveolar type 2 cell",
                    "match_mode": "state_stripped_alias",
                    "lost_modifiers": ["transitional"],
                },
            ],
        },
    )

    raw = load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
    result = json.loads(raw)

    assert result["errors"] == []
    assert "celltype_resolution.json" in result["files"]
    loaded = result["files"]["celltype_resolution.json"]
    assert loaded["interest_celltypes"] == ["AT2", "Transitional AT2"]
    assert loaded["primary_resolved_celltype"] == "pulmonary alveolar type 2 cell"


def test_celltype_resolution_is_loaded_but_denied_as_support_citation(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_json(
        evidence / "assessment_results.json",
        {"stage3_candidates": [{"gene": "FN1"}]},
    )
    _write_json(evidence / "gene_manifest.json", {"genes": ["FN1"]})
    _write_json(evidence / "known_drugs.json", {"disease": "pulmonary fibrosis"})
    _write_json(evidence / "stage1_filter_results.json", [])
    _write_json(
        evidence / "celltype_resolution.json",
        {
            "interest_celltypes": ["AT2", "Transitional AT2"],
            "primary_resolved_celltype": "pulmonary alveolar type 2 cell",
            "matches": [],
        },
    )

    loaded = json.loads(
        load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
    )
    validation = json.loads(
        validate_evidence_references.invoke({
            "data_dir": str(tmp_path),
            "references": ["celltype_resolution.json"],
        })
    )

    assert "celltype_resolution.json" in loaded["files"]
    assert validation["valid"] is False
    assert validation["invalid_references"] == ["celltype_resolution.json"]
    assert validation["denied_citations"] == [
        {
            "reference": "celltype_resolution.json",
            "token": "celltype_resolution.json",
            "reason": (
                "context-only cell-type resolution; cite Stage 1 pair files "
                "for Census evidence."
            ),
        }
    ]


def test_hypothesis_scope_classifies_passed_stage1_celltype_usage(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "MUC1", "ITGB2", "FN1", "SDC2"])
    _write_stage1_filter_results(
        evidence,
        [
            ("ICAM1", "MUC1", True),
            ("ICAM1", "ITGB2", True),
            ("FN1", "SDC2", True),
        ],
    )
    _write_stage1_pair(
        evidence,
        "ICAM1",
        "MUC1",
        gene_a_diff=0.2,
        gene_b_diff=0.3,
        coexpr_diff=0.4,
    )
    _write_stage1_pair(
        evidence,
        "ICAM1",
        "ITGB2",
        gene_a_diff=0.2,
        gene_b_diff=-0.3,
        coexpr_diff=-0.2,
    )
    _write_stage1_pair(
        evidence,
        "FN1",
        "SDC2",
        gene_a_diff=-0.4,
        gene_b_diff=-0.3,
        coexpr_diff=-0.2,
    )

    loaded = json.loads(
        load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
    )
    validation = json.loads(
        validate_evidence_references.invoke({
            "data_dir": str(tmp_path),
            "references": [
                "stage1_ICAM1--MUC1.json",
                "stage1_ICAM1--ITGB2.json",
                "stage1_FN1--SDC2.json",
            ],
        })
    )

    assert loaded["interest_cell_intrinsic_stage1_pair_files"] == [
        "stage1_ICAM1--MUC1.json"
    ]
    assert loaded["spatial_niche_only_stage1_pair_files"] == [
        "stage1_FN1--SDC2.json",
        "stage1_ICAM1--ITGB2.json",
    ]
    assert validation["interest_cell_intrinsic_stage1_pair_files"] == [
        "stage1_ICAM1--MUC1.json"
    ]
    policy = {
        item["filename"]: item
        for item in validation["stage1_pair_usage_guidance"]
    }
    assert policy["stage1_ICAM1--MUC1.json"]["usage"] == "interest_cell_intrinsic"
    assert policy["stage1_ICAM1--ITGB2.json"]["usage"] == "spatial_niche_only"
    assert policy["stage1_ICAM1--ITGB2.json"]["target_cell_depleted_metrics"] == [
        "gene_b",
        "coexpression",
    ]
    assert policy["stage1_FN1--SDC2.json"]["target_cell_depleted_metrics"] == [
        "gene_a",
        "gene_b",
        "coexpression",
    ]


def test_save_hypothesis_report_rejects_celltype_resolution_support_citation(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_json(
        evidence / "assessment_results.json",
        {"stage3_candidates": [{"gene": "FN1"}]},
    )
    _write_json(evidence / "stage3_FN1.json", {"gene": "FN1"})
    _write_json(evidence / "stage1_filter_results.json", [])
    _write_json(
        evidence / "celltype_resolution.json",
        {
            "interest_celltypes": ["AT2", "Transitional AT2"],
            "primary_resolved_celltype": "pulmonary alveolar type 2 cell",
            "matches": [],
        },
    )
    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "AT2-focused FN1 hypothesis",
                "category": "Mechanism of Action",
                "core_claim": "FN1 biology is testable in AT2-focused context.",
                "evidence_references": ["celltype_resolution.json", "stage3_FN1.json"],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["FN1"],
                    "pathways": [],
                    "cell_types": ["AT2", "pulmonary alveolar type 2 cell"],
                    "drugs": [],
                },
                "falsifiable_prediction": "Qualitative FN1 perturbation response.",
                "validation_approach": "Assay FN1 perturbation.",
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
            "total_evidence_files": 2,
            "referenced_files": 2,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "celltype_resolution.json" in error
        and "context-only cell-type resolution" in error
        for error in result["errors"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_hypothesis_prompt_requires_interest_celltype_focus() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "celltype_resolution.json" in text
    assert "interest_celltypes" in text
    assert "lost_modifiers" in text
    assert "semantic_proxy" in text
    assert "proxy validation" in text
    assert "biological_entities.cell_types" in text
    assert "Do not claim that Census separately validated a lost state modifier" in text
    assert (
        "Do not claim that Census separately validated the original state-specific label"
        in text
    )
    assert "must not appear in `evidence_references`" in text
    assert "cite Stage 1 pair files for Census evidence" in text
    assert "AT2" in text
    assert "Transitional AT2" in text
    assert "Direct pair-axis claims require direct Stage 1 pair evidence" in text
    assert "Do not title a hypothesis `A-B axis` unless" in text
    assert "target-vs-rest direction" in text
    assert "target-cell-depleted" in text
    assert "validation_approach must mention" in text
    assert "Biological Grounding" in text
    assert "Target-Disease Support" in text
    assert "Actionability" in text
    assert "Interpretation Constraint" in text
    assert "Stage 2 OpenTargets" in text
    assert "target-disease support, not causal biology" in text
    assert "Stage 3" in text
    assert "actionability" in text
    assert "not biological causality" in text
    assert "Primary epithelial/AT2-intrinsic follow-up recommendations" in text
    assert (
        "Secondary epithelial-associated spatial-niche follow-up recommendations"
        in text
    )
    assert "epithelial-cell-intrinsic" in text
    assert "target mechanisms" in text
    assert "Evidence-Grounded Follow-up Recommendation Generation" in text
    assert "Conservative Interpretation" in text
    assert "Recommended Follow-up Test" in text
    assert "Not yet established:" in text
    assert "functional axis" in text
    assert "major source" in text
    assert "synergistic" in text
    assert "Stage 1 Census coexpression supports enrichment/depletion" in text
    assert "prioritizes" in text
    assert "nominates" in text
    assert "spatial-niche follow-up candidate" in text
    assert "cross-cell candidate" in text
    assert "test whether ... changes" in text
    assert "should reduce" in text
    assert "blockade for reducing" in text
    assert "barrier dysfunction" in text
    assert "secondary Stage 1 framing evidence table" in text
    assert (
        "cite depleted Stage 1 pair files when the recommendation names that pair concept"
        in text
    )
    assert "not as AT2-intrinsic support" in text
    assert "target-cell-depleted Stage 1 pair files may appear" in text


def test_save_hypothesis_report_rejects_direct_pair_axis_without_matching_stage1_file(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["FN1", "ITGB2"])
    _write_stage1_filter_results(evidence, [("FN1", "SDC2", True)])
    _write_stage1_pair(evidence, "FN1", "SDC2")

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "FN1-ITGB2 Integrin Axis Drives Fibroblast Activation in IPF",
                "category": "Mechanism of Action",
                "core_claim": (
                    "FN1 binds to ITGB2 and forms a direct integrin axis in IPF. "
                    "The cited Stage 1 evidence is FN1--SDC2, not FN1--ITGB2."
                ),
                "evidence_references": [
                    "stage1_FN1--SDC2.json",
                    "stage3_FN1.json",
                    "stage3_ITGB2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["FN1", "ITGB2", "SDC2"],
                    "pathways": ["integrin signaling"],
                    "cell_types": ["pulmonary alveolar type 2 cell", "fibroblast"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "FN1 knockdown will alter ITGB2-dependent adhesion in AT2-fibroblast "
                    "co-culture."
                ),
                "validation_approach": (
                    "Primary IPF AT2 and fibroblast co-culture with FN1 knockdown."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 3,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "claims direct pair axis 'FN1--ITGB2'" in error
        and "stage1_FN1--ITGB2.json" in error
        for error in result["errors"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_accepts_reverse_stage1_pair_citation_for_direct_claim(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "ITGB2"])
    _write_stage1_filter_results(evidence, [("ICAM1", "ITGB2", True)])
    _write_stage1_pair(evidence, "ICAM1", "ITGB2")

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "AT2 epithelial ITGB2-ICAM1 axis follow-up hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "The ITGB2--ICAM1 direct pair axis is supported by the cited "
                    "reverse-ordered Stage 1 file and motivates AT2 epithelial "
                    "follow-up testing."
                ),
                "evidence_references": [
                    "stage1_ICAM1--ITGB2.json",
                    "stage3_ICAM1.json",
                    "stage3_ITGB2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ITGB2", "ICAM1"],
                    "pathways": ["adhesion"],
                    "cell_types": ["AT2", "pulmonary alveolar type 2 cell"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "ITGB2 perturbation will change ICAM1-linked epithelial adhesion readouts."
                ),
                "validation_approach": (
                    "Primary IPF pulmonary alveolar type 2 cell assay with ITGB2 "
                    "perturbation and ICAM1 readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is True, result


def test_save_hypothesis_report_rejects_missing_reverse_stage1_citation_names_available_file(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "ITGB2"])
    _write_stage1_filter_results(evidence, [("ICAM1", "ITGB2", True)])
    _write_stage1_pair(evidence, "ICAM1", "ITGB2")

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "ITGB2-ICAM1 axis follow-up hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "The ITGB2--ICAM1 direct pair axis is proposed, but the "
                    "matching reverse Stage 1 file is not cited."
                ),
                "evidence_references": [
                    "stage3_ICAM1.json",
                    "stage3_ITGB2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ITGB2", "ICAM1"],
                    "pathways": ["adhesion"],
                    "cell_types": ["fibroblast"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "ITGB2 perturbation will change ICAM1-linked adhesion readouts."
                ),
                "validation_approach": "Primary IPF fibroblast co-culture assay.",
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 2,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "claims direct pair axis 'ITGB2--ICAM1'" in error
        and "canonical_existing=stage1_ICAM1--ITGB2.json" in error
        and "available_passed=true" in error
        for error in result["errors"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_reverse_stage1_pair_when_filter_failed(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "ITGB2"])
    _write_stage1_filter_results(evidence, [("ICAM1", "ITGB2", False)])
    _write_stage1_pair(evidence, "ICAM1", "ITGB2", passed=False)

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "ITGB2-ICAM1 failed pair axis hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "The ITGB2--ICAM1 direct pair axis is claimed despite a failed "
                    "reverse Stage 1 filter result."
                ),
                "evidence_references": [
                    "stage1_ICAM1--ITGB2.json",
                    "stage3_ICAM1.json",
                    "stage3_ITGB2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ITGB2", "ICAM1"],
                    "pathways": ["adhesion"],
                    "cell_types": ["fibroblast"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "ITGB2 perturbation will change ICAM1-linked adhesion readouts."
                ),
                "validation_approach": "Primary IPF fibroblast co-culture assay.",
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "ICAM1--ITGB2" in error and "without proven passed=true status" in error
        for error in result["errors"]
    )
    assert any("ICAM1--ITGB2" in v for v in result.get("failed_pair_violations", []))
    assert not (evidence / "hypothesis_report.json").exists()


def test_hypothesis_quality_reports_grounding_violations_for_existing_artifact(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["FN1", "ITGB2", "SDC2", "CD4"])
    _write_stage1_filter_results(
        evidence,
        [
            ("FN1", "SDC2", True),
            ("FN1", "CD4", True),
        ],
    )
    _write_stage1_pair(evidence, "FN1", "SDC2")
    _write_stage1_pair(evidence, "FN1", "CD4")

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 4,
        "hypotheses_retained": 4,
        "hypotheses": [
            {
                "rank": 1,
                "title": "FN1-ITGB2 Integrin Axis Drives Fibroblast Activation in IPF",
                "category": "Mechanism of Action",
                "gap_type": "none",
                "core_claim": (
                    "FN1 binds to ITGB2 and forms a direct integrin axis in IPF. "
                    "The cited Stage 1 evidence is FN1--SDC2, not FN1--ITGB2."
                ),
                "evidence_references": [
                    "stage1_FN1--SDC2.json",
                    "stage3_FN1.json",
                    "stage3_ITGB2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["FN1", "ITGB2", "SDC2"],
                    "pathways": ["integrin signaling"],
                    "cell_types": ["fibroblast"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "FN1 knockdown will alter ITGB2-dependent adhesion in co-culture."
                ),
                "validation_approach": (
                    "Primary IPF fibroblast co-culture with FN1 knockdown."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            },
            {
                "rank": 2,
                "title": "FN1-SDC2 therapeutic strategy",
                "category": "Therapeutic Strategy",
                "gap_type": "none",
                "core_claim": "FN1--SDC2 is testable as a therapeutic strategy in IPF.",
                "evidence_references": ["stage1_FN1--SDC2.json", "stage3_SDC2.json"],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["FN1", "SDC2"],
                    "pathways": ["matrix remodeling"],
                    "cell_types": ["fibroblast"],
                    "drugs": [],
                },
                "falsifiable_prediction": "FN1 perturbation will alter SDC2 signaling.",
                "validation_approach": "Primary IPF fibroblast assay with FN1 knockdown.",
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            },
            {
                "rank": 3,
                "title": "FN1-CD4 cross-target interaction",
                "category": "Cross-Target Interaction",
                "gap_type": "none",
                "core_claim": "FN1--CD4 is testable as a cross-target interaction in IPF.",
                "evidence_references": ["stage1_FN1--CD4.json", "stage3_CD4.json"],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["FN1", "CD4"],
                    "pathways": ["immune remodeling"],
                    "cell_types": ["fibroblast"],
                    "drugs": [],
                },
                "falsifiable_prediction": "FN1 perturbation will alter CD4-linked signaling.",
                "validation_approach": "Primary IPF fibroblast assay with FN1 knockdown.",
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            },
            {
                "rank": 4,
                "title": "FN1 matrix remodeling pathway",
                "category": "Novel Pathway",
                "gap_type": "none",
                "core_claim": "FN1 matrix remodeling is testable in IPF biology.",
                "evidence_references": ["stage3_FN1.json"],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["FN1"],
                    "pathways": ["matrix remodeling"],
                    "cell_types": ["fibroblast"],
                    "drugs": [],
                },
                "falsifiable_prediction": "FN1 perturbation will alter matrix remodeling markers.",
                "validation_approach": "Primary IPF fibroblast assay with FN1 knockdown.",
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            },
        ],
        "gap_analysis": {
            "total_evidence_files": 8,
            "referenced_files": 6,
            "orphan_files": [],
        },
    }
    _write_json(evidence / "hypothesis_report.json", report)

    result = validate_hypothesis_report_quality(tmp_path)

    assert result["valid"] is False
    assert any(
        error["code"] == "HYPOTHESIS_GROUNDING_VIOLATION"
        for error in result["errors"]
    )
    assert any(
        "claims direct pair axis 'FN1--ITGB2'" in error
        and "stage1_FN1--ITGB2.json" in error
        for error in result["hypothesis_grounding_violations"]
    )


def test_save_hypothesis_report_rejects_explicit_pair_axis_missing_from_entities(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["FN1", "ITGB2"])
    _write_stage1_filter_results(evidence, [("FN1", "SDC2", True)])
    _write_stage1_pair(evidence, "FN1", "SDC2")

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "FN1-ITGB2 Integrin Axis Drives Fibroblast Activation in IPF",
                "category": "Mechanism of Action",
                "core_claim": (
                    "FN1-ITGB2 is a direct pair axis in IPF, but the cited Stage 1 "
                    "evidence is FN1--SDC2."
                ),
                "evidence_references": [
                    "stage1_FN1--SDC2.json",
                    "stage3_FN1.json",
                    "stage3_ITGB2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["FN1", "SDC2"],
                    "pathways": ["integrin signaling"],
                    "cell_types": ["pulmonary alveolar type 2 cell", "fibroblast"],
                    "drugs": [],
                },
                "falsifiable_prediction": "FN1 knockdown will alter adhesion.",
                "validation_approach": "Primary IPF AT2 co-culture with FN1 knockdown.",
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 3,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any("claims direct pair axis 'FN1--ITGB2'" in error for error in result["errors"])
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_at2_celltype_when_validation_omits_at2(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["FN1", "SDC2"])
    _write_stage1_filter_results(evidence, [("FN1", "SDC2", True)])
    _write_stage1_pair(evidence, "FN1", "SDC2")

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "AT2 FN1-SDC2 pair hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "FN1--SDC2 is a direct Census-supported pair in the resolved "
                    "AT2 context."
                ),
                "evidence_references": [
                    "stage1_FN1--SDC2.json",
                    "stage3_FN1.json",
                    "stage3_SDC2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["FN1", "SDC2"],
                    "pathways": ["integrin signaling"],
                    "cell_types": ["pulmonary alveolar type 2 cell", "fibroblast"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "FN1 perturbation will alter SDC2-linked epithelial remodeling."
                ),
                "validation_approach": (
                    "Primary IPF fibroblast monoculture with FN1 knockdown and SDC2 "
                    "readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "lists interest/resolved cell type" in error
        and "validation_approach" in error
        for error in result["errors"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_at2_substring_gene_in_validation(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["FN1", "SDC2"])
    _write_stage1_filter_results(evidence, [("FN1", "SDC2", True)])
    _write_stage1_pair(evidence, "FN1", "SDC2")

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "AT2 FN1-SDC2 pair hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "FN1--SDC2 is a direct Census-supported pair in the resolved "
                    "AT2 context."
                ),
                "evidence_references": [
                    "stage1_FN1--SDC2.json",
                    "stage3_FN1.json",
                    "stage3_SDC2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["FN1", "SDC2"],
                    "pathways": ["integrin signaling"],
                    "cell_types": ["AT2"],
                    "drugs": [],
                },
                "falsifiable_prediction": "AT2 FN1 perturbation will change SDC2 signaling.",
                "validation_approach": "STAT2 knockdown in fibroblast monoculture.",
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "lists interest/resolved cell type" in error
        and "validation_approach" in error
        for error in result["errors"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_target_depleted_stage1_as_at2_support(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["FN1", "SDC2"])
    _write_stage1_filter_results(evidence, [("FN1", "SDC2", True)])
    _write_stage1_pair(
        evidence,
        "FN1",
        "SDC2",
        gene_a_diff=-0.2,
        gene_b_diff=-0.1,
        coexpr_diff=-0.05,
    )

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "AT2 FN1-SDC2 depleted pair hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "FN1--SDC2 is interpreted as support for AT2 remodeling despite "
                    "negative target-vs-rest direction."
                ),
                "evidence_references": [
                    "stage1_FN1--SDC2.json",
                    "stage3_FN1.json",
                    "stage3_SDC2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["FN1", "SDC2"],
                    "pathways": ["integrin signaling"],
                    "cell_types": ["AT2"],
                    "drugs": [],
                },
                "falsifiable_prediction": "AT2 FN1 perturbation will change SDC2 signaling.",
                "validation_approach": (
                    "Primary IPF AT2 culture with FN1 knockdown and SDC2 readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "target-cell-depleted Stage 1 Census evidence" in error
        and "stage1_FN1--SDC2.json" in error
        for error in result["errors"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_coexpr_depleted_pair_as_at2_intrinsic(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "ITGB2"])
    _write_stage1_filter_results(evidence, [("ICAM1", "ITGB2", True)])
    _write_stage1_pair(
        evidence,
        "ICAM1",
        "ITGB2",
        gene_a_diff=0.3,
        gene_b_diff=0.1,
        coexpr_diff=-0.05,
    )

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "AT2 ICAM1-ITGB2 intrinsic coexpression hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "ICAM1--ITGB2 is interpreted as an AT2-intrinsic "
                    "same-cell coexpression axis in IPF."
                ),
                "evidence_references": [
                    "stage1_ICAM1--ITGB2.json",
                    "stage3_ICAM1.json",
                    "stage3_ITGB2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ICAM1", "ITGB2"],
                    "pathways": ["adhesion"],
                    "cell_types": ["AT2"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "AT2 ICAM1 perturbation will change same-cell ITGB2 signaling."
                ),
                "validation_approach": (
                    "Primary IPF AT2 culture with ICAM1 knockdown and ITGB2 readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "coexpression-depleted Stage 1 Census evidence" in error
        and "stage1_ICAM1--ITGB2.json" in error
        for error in result["errors"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_mixed_cross_cell_intrinsic_depleted_pair(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "ITGB2"])
    _write_stage1_filter_results(evidence, [("ICAM1", "ITGB2", True)])
    _write_stage1_pair(
        evidence,
        "ICAM1",
        "ITGB2",
        gene_a_diff=0.3,
        gene_b_diff=0.1,
        coexpr_diff=-0.05,
    )

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "AT2 ICAM1-ITGB2 mixed spatial hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "ICAM1--ITGB2 is a cross-cell spatial niche signal, but also "
                    "an AT2-intrinsic same-cell coexpression axis in IPF."
                ),
                "evidence_references": [
                    "stage1_ICAM1--ITGB2.json",
                    "stage3_ICAM1.json",
                    "stage3_ITGB2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ICAM1", "ITGB2"],
                    "pathways": ["adhesion"],
                    "cell_types": ["AT2"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "AT2 ICAM1 perturbation will change same-cell ITGB2 signaling."
                ),
                "validation_approach": (
                    "Primary IPF AT2 culture with ICAM1 knockdown and ITGB2 readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "coexpression-depleted Stage 1 Census evidence" in error
        and "stage1_ICAM1--ITGB2.json" in error
        for error in result["errors"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_depleted_gene_on_interest_cell_claim(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "ITGB2"])
    _write_stage1_filter_results(evidence, [("ICAM1", "ITGB2", True)])
    _write_stage1_pair(
        evidence,
        "ICAM1",
        "ITGB2",
        gene_a_diff=0.3,
        gene_b_diff=-0.1,
        coexpr_diff=0.05,
    )

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "ICAM1-ITGB2 epithelial localization hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "ICAM1 expressed in AT2 cells binds ITGB2 on pulmonary "
                    "alveolar type 2 cells to drive epithelial remodeling."
                ),
                "evidence_references": [
                    "stage1_ICAM1--ITGB2.json",
                    "stage3_ICAM1.json",
                    "stage3_ITGB2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ICAM1", "ITGB2"],
                    "pathways": ["adhesion"],
                    "cell_types": ["pulmonary alveolar type 2 cell"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "AT2 ICAM1 perturbation will change ITGB2 localization."
                ),
                "validation_approach": (
                    "Primary IPF pulmonary alveolar type 2 cell culture with "
                    "ICAM1 knockdown and ITGB2 readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "target-cell-depleted gene expression claim" in error
        and "ITGB2" in error
        and "stage1_ICAM1--ITGB2.json" in error
        for error in result["errors"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_accepts_at2_grounded_direct_pair_hypothesis(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["FN1", "SDC2"])
    _write_stage1_filter_results(evidence, [("FN1", "SDC2", True)])
    _write_stage1_pair(
        evidence,
        "FN1",
        "SDC2",
        gene_a_diff=0.35,
        gene_b_diff=0.22,
        coexpr_diff=0.11,
    )

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "AT2 FN1-SDC2 enriched pair hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "FN1--SDC2 is a direct Census-supported pair enriched in the "
                    "resolved AT2 context."
                ),
                "evidence_references": [
                    "stage1_FN1--SDC2.json",
                    "stage3_FN1.json",
                    "stage3_SDC2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["FN1", "SDC2"],
                    "pathways": ["integrin signaling"],
                    "cell_types": ["pulmonary alveolar type 2 cell"],
                    "drugs": [],
                },
                "falsifiable_prediction": "AT2 FN1 perturbation will change SDC2 signaling.",
                "validation_approach": (
                    "Primary IPF AT2 culture with FN1 knockdown and SDC2 readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is True
    assert result["errors"] == []
    assert (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_accepts_reverse_stage1_direct_pair_citation(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "ITGB2"])
    _write_stage1_filter_results(evidence, [("ICAM1", "ITGB2", True)])
    _write_stage1_pair(
        evidence,
        "ICAM1",
        "ITGB2",
        gene_a_diff=0.35,
        gene_b_diff=0.22,
        coexpr_diff=0.11,
    )

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "AT2 ITGB2-ICAM1 reverse-cited pair hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "ITGB2--ICAM1 is a direct Census-supported pair enriched in "
                    "the resolved AT2 context, citing the ligand-receptor ordered "
                    "Stage 1 file."
                ),
                "evidence_references": [
                    "stage1_ICAM1--ITGB2.json",
                    "stage3_ICAM1.json",
                    "stage3_ITGB2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ITGB2", "ICAM1"],
                    "pathways": ["adhesion"],
                    "cell_types": ["pulmonary alveolar type 2 cell"],
                    "drugs": [],
                },
                "falsifiable_prediction": "AT2 ITGB2 perturbation will change ICAM1 signaling.",
                "validation_approach": (
                    "Primary IPF AT2 culture with ITGB2 perturbation and ICAM1 readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is True
    assert result["errors"] == []
    assert (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_reverse_stage1_claim_without_citation(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "ITGB2"])
    _write_stage1_filter_results(evidence, [("ICAM1", "ITGB2", True)])
    _write_stage1_pair(evidence, "ICAM1", "ITGB2")

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "AT2 ITGB2-ICAM1 direct pair hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "ITGB2--ICAM1 is a direct Census-supported pair enriched in "
                    "the resolved AT2 context, but the Stage 1 pair file is omitted."
                ),
                "evidence_references": ["stage3_ICAM1.json", "stage3_ITGB2.json"],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ITGB2", "ICAM1"],
                    "pathways": ["adhesion"],
                    "cell_types": ["pulmonary alveolar type 2 cell"],
                    "drugs": [],
                },
                "falsifiable_prediction": "AT2 ITGB2 perturbation will change ICAM1 signaling.",
                "validation_approach": (
                    "Primary IPF AT2 culture with ITGB2 perturbation and ICAM1 readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 2,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "claims direct pair axis 'ITGB2--ICAM1'" in error
        and "stage1_ICAM1--ITGB2.json (passed=true)" in error
        for error in result["errors"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_failed_reverse_stage1_pair_guardrail(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "ITGB2"])
    _write_stage1_filter_results(evidence, [("ICAM1", "ITGB2", False)])
    _write_stage1_pair(evidence, "ICAM1", "ITGB2", passed=False)

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "AT2 ITGB2-ICAM1 failed reverse pair hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "ITGB2--ICAM1 is a direct pair axis in IPF despite the "
                    "failed Stage 1 filter result."
                ),
                "evidence_references": [
                    "stage1_ICAM1--ITGB2.json",
                    "stage3_ICAM1.json",
                    "stage3_ITGB2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ITGB2", "ICAM1"],
                    "pathways": ["adhesion"],
                    "cell_types": ["pulmonary alveolar type 2 cell"],
                    "drugs": [],
                },
                "falsifiable_prediction": "AT2 ITGB2 perturbation will change ICAM1 signaling.",
                "validation_approach": (
                    "Primary IPF AT2 culture with ITGB2 perturbation and ICAM1 readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 3,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "failed Stage 1 pair 'ICAM1--ITGB2'" in error
        for error in result["failed_pair_violations"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_cited_but_unverified_numeric_prediction(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["FN1", "SDC2"])
    _write_stage1_filter_results(evidence, [("FN1", "SDC2", True)])
    _write_stage1_pair(
        evidence,
        "FN1",
        "SDC2",
        gene_a_diff=0.35,
        gene_b_diff=0.22,
        coexpr_diff=0.11,
    )

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "AT2 FN1-SDC2 enriched pair hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "FN1--SDC2 is a direct Census-supported pair enriched in the "
                    "resolved AT2 context."
                ),
                "evidence_references": [
                    "stage1_FN1--SDC2.json",
                    "stage3_FN1.json",
                    "stage3_SDC2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["FN1", "SDC2"],
                    "pathways": ["integrin signaling"],
                    "cell_types": ["pulmonary alveolar type 2 cell"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "from stage1_FN1--SDC2.json, FN1 perturbation will reduce "
                    "SDC2 signaling by at least 70% versus controls."
                ),
                "validation_approach": (
                    "Primary IPF AT2 culture with FN1 knockdown and SDC2 readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any("fabricated or non-evidence-derived numeric" in error for error in result["errors"])
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_accepts_depleted_pair_as_secondary_spatial_niche(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "ITGB2"])
    _write_stage1_filter_results(evidence, [("ICAM1", "ITGB2", True)])
    _write_stage1_pair(
        evidence,
        "ICAM1",
        "ITGB2",
        gene_a_diff=0.3,
        gene_b_diff=-0.2,
        coexpr_diff=-0.05,
    )

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "ICAM1-ITGB2 spatial-niche follow-up candidate",
                "category": "Mechanism of Action",
                "core_claim": (
                    "stage1_ICAM1--ITGB2.json shows AT2 coexpression is depleted, "
                    "so this pair is retained as cross-cell spatial-niche framing "
                    "evidence, not as AT2-intrinsic support. Not yet established: "
                    "whether ICAM1 and ITGB2 mark interacting epithelial and "
                    "leukocyte neighborhoods."
                ),
                "evidence_references": [
                    "stage1_ICAM1--ITGB2.json",
                    "stage3_ICAM1.json",
                    "stage3_ITGB2.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ICAM1", "ITGB2"],
                    "pathways": ["adhesion"],
                    "cell_types": ["leukocyte", "epithelial-associated niche"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "test whether ICAM1-high epithelial neighborhoods change "
                    "adjacency to ITGB2-positive leukocytes in spatial data."
                ),
                "validation_approach": (
                    "Spatial neighborhood analysis and leukocyte-epithelial "
                    "co-culture assays without treating the pair as AT2 same-cell "
                    "coexpression."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is True, result
    assert result["errors"] == []
    assert (evidence / "hypothesis_report.json").exists()


def test_hypothesis_grounding_rejects_unsupported_success_title_wording(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    report = {
        "hypotheses": [
            {
                "title": "ITGB2 integrin blockade for reducing leukocyte infiltration in IPF",
                "core_claim": "Stage 3 target evidence nominates ITGB2 for follow-up.",
                "falsifiable_prediction": "test whether ITGB2 perturbation changes migration.",
                "evidence_references": ["stage3_ITGB2.json"],
                "biological_entities": {
                    "genes": ["ITGB2"],
                    "pathways": ["cell adhesion"],
                    "cell_types": ["leukocyte"],
                    "drugs": [],
                },
            }
        ]
    }

    errors = validate_hypothesis_grounding(report, evidence)

    assert any("unsupported causal or therapeutic-success wording" in error for error in errors)
    assert any("blockade for reducing" in error for error in errors)


def test_hypothesis_grounding_allows_overclaim_phrase_inside_caveat(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    report = {
        "hypotheses": [
            {
                "title": "ITGB2 leukocyte-adhesion gene-level follow-up candidate",
                "core_claim": (
                    "Stage 3 target evidence nominates ITGB2 for follow-up. "
                    "Not yet established: whether ITGB2 blockade for reducing "
                    "leukocyte infiltration would work in IPF."
                ),
                "falsifiable_prediction": "test whether ITGB2 perturbation changes migration.",
                "evidence_references": ["stage3_ITGB2.json"],
                "biological_entities": {
                    "genes": ["ITGB2"],
                    "pathways": ["cell adhesion"],
                    "cell_types": ["leukocyte"],
                    "drugs": [],
                },
            }
        ]
    }

    assert validate_hypothesis_grounding(report, evidence) == []


def test_hypothesis_grounding_rejects_nonconservative_followup_language(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    report = {
        "hypotheses": [
            {
                "title": (
                    "CD47 macrophage-fibroblast crosstalk therapeutic strategy "
                    "with fibrosis resolution readouts"
                ),
                "core_claim": (
                    "Stage 3 target evidence nominates CD47 for follow-up. "
                    "Not yet established: whether CD47 blockade alters fibrosis "
                    "resolution or requires combination approaches."
                ),
                "falsifiable_prediction": (
                    "Test whether CD47 perturbation changes macrophage-fibroblast "
                    "readouts."
                ),
                "validation_approach": (
                    "Evaluate additive vs. synergistic effects in co-culture."
                ),
                "evidence_references": ["stage3_CD47.json", "ot_CD47.json"],
                "biological_entities": {
                    "genes": ["CD47"],
                    "pathways": ["macrophage-fibroblast crosstalk"],
                    "cell_types": ["macrophage", "fibroblast"],
                    "drugs": [],
                },
            }
        ]
    }

    errors = validate_hypothesis_grounding(report, evidence)

    assert any("non-conservative follow-up wording" in error for error in errors)
    assert any("therapeutic strategy" in error for error in errors)
    assert any("cd47 blockade alters fibrosis resolution" in error for error in errors)
    assert any("synergistic effects" in error for error in errors)


def test_hypothesis_grounding_rejects_spatial_niche_without_stage1_reference(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    report = {
        "hypotheses": [
            {
                "title": "CD4 epithelial-immune interface spatial-niche follow-up candidate",
                "core_claim": (
                    "CD4 has Stage 3 evidence and appears in Stage 1 pair context. "
                    "This is a gene-level follow-up candidate."
                ),
                "falsifiable_prediction": (
                    "Test whether CD4+ T cell activation changes fibroblast readouts."
                ),
                "validation_approach": "Immune-fibroblast co-culture readouts.",
                "evidence_references": ["stage3_CD4.json", "ot_CD4.json"],
                "biological_entities": {
                    "genes": ["CD4"],
                    "pathways": ["T cell activation"],
                    "cell_types": ["T cell"],
                    "drugs": [],
                },
            }
        ]
    }

    errors = validate_hypothesis_grounding(report, evidence)

    assert any("gene-level evidence as spatial" in error for error in errors)
    assert any("spatial-niche label without Stage 1" in error for error in errors)
    assert any("Stage 1 pair context without cited Stage 1" in error for error in errors)


def test_save_hypothesis_report_rejects_intrinsic_pair_as_fibroblast_only(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "MUC1"])
    _write_stage1_filter_results(evidence, [("ICAM1", "MUC1", True)])
    _write_stage1_pair(
        evidence,
        "ICAM1",
        "MUC1",
        gene_a_diff=0.35,
        gene_b_diff=0.28,
        coexpr_diff=0.18,
    )

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "ICAM1-MUC1 fibroblast feedback hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "ICAM1--MUC1 is interpreted as a fibroblast feedback loop "
                    "despite being target-cell-intrinsic Stage 1 evidence."
                ),
                "evidence_references": [
                    "stage1_ICAM1--MUC1.json",
                    "stage3_ICAM1.json",
                    "stage3_MUC1.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ICAM1", "MUC1"],
                    "pathways": ["NF-kB signaling"],
                    "cell_types": ["fibroblast"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "MUC1 knockdown will reduce ICAM1 activation in IPF fibroblasts."
                ),
                "validation_approach": (
                    "Primary IPF fibroblast monoculture with MUC1 knockdown and "
                    "ICAM1 readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "target-cell-intrinsic Stage 1 evidence" in error for error in result["errors"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_intrinsic_pair_with_unrelated_epithelial_validation(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "MUC1"])
    _write_stage1_filter_results(evidence, [("ICAM1", "MUC1", True)])
    _write_stage1_pair(
        evidence,
        "ICAM1",
        "MUC1",
        gene_a_diff=0.35,
        gene_b_diff=0.28,
        coexpr_diff=0.18,
    )

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "ICAM1-MUC1 unrelated epithelial hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "ICAM1--MUC1 is interpreted as a generic epithelial cell "
                    "program without anchoring the AT2 pulmonary epithelial context."
                ),
                "evidence_references": [
                    "stage1_ICAM1--MUC1.json",
                    "stage3_ICAM1.json",
                    "stage3_MUC1.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ICAM1", "MUC1"],
                    "pathways": ["NF-kB signaling"],
                    "cell_types": ["intestinal epithelial cells"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "MUC1 perturbation will alter ICAM1-linked inflammatory signaling."
                ),
                "validation_approach": (
                    "Intestinal epithelial cells with MUC1 knockdown and ICAM1 readout."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "target-cell-intrinsic Stage 1 evidence" in error
        and "stage1_ICAM1--MUC1.json" in error
        for error in result["errors"]
    )
    assert not (evidence / "hypothesis_report.json").exists()


def test_save_hypothesis_report_accepts_intrinsic_pair_with_epithelial_validation(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    _write_hypothesis_context(evidence, ["ICAM1", "MUC1"])
    _write_stage1_filter_results(evidence, [("ICAM1", "MUC1", True)])
    _write_stage1_pair(
        evidence,
        "ICAM1",
        "MUC1",
        gene_a_diff=0.35,
        gene_b_diff=0.28,
        coexpr_diff=0.18,
    )

    report = {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "ICAM1-MUC1 epithelial program hypothesis",
                "category": "Mechanism of Action",
                "core_claim": (
                    "ICAM1--MUC1 is interpreted as an AT2 epithelial spatial "
                    "program in pulmonary fibrosis."
                ),
                "evidence_references": [
                    "stage1_ICAM1--MUC1.json",
                    "stage3_ICAM1.json",
                    "stage3_MUC1.json",
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": ["ICAM1", "MUC1"],
                    "pathways": ["NF-kB signaling"],
                    "cell_types": ["alveolar epithelial cells", "fibroblast"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "MUC1 perturbation will alter ICAM1-linked inflammatory "
                    "signaling in AT2 epithelial cells."
                ),
                "validation_approach": (
                    "IPF-derived alveolar epithelial cells co-cultured with "
                    "fibroblasts, with MUC1 knockdown and ICAM1/NF-kB readouts."
                ),
                "scores": {
                    "evidence_coverage": 0.8,
                    "specificity": 0.8,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.73,
                },
            }
        ],
        "gap_analysis": {
            "total_evidence_files": 4,
            "referenced_files": 3,
            "orphan_files": [],
        },
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(tmp_path), "report": report})
    )

    assert result["saved"] is True
    assert result["errors"] == []
    assert (evidence / "hypothesis_report.json").exists()


def test_hypothesis_grounding_uses_gene_boundaries_for_loose_pair_cues(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    report = {
        "hypotheses": [
            {
                "title": "Fibroblast SDC2 axis",
                "core_claim": "Fibroblast activation involves an SDC2 signaling axis.",
                "falsifiable_prediction": "",
                "evidence_references": [],
                "biological_entities": {
                    "genes": ["F", "SDC2"],
                    "pathways": [],
                    "cell_types": ["fibroblast"],
                    "drugs": [],
                },
            }
        ]
    }

    assert validate_hypothesis_grounding(report, evidence) == []


def test_hypothesis_grounding_preserves_known_hyphenated_gene_mentions(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    report = {
        "hypotheses": [
            {
                "title": "HLA-DRA antigen presentation axis",
                "core_claim": (
                    "HLA-DRA supports antigen presentation in IPF without claiming a "
                    "direct receptor pair."
                ),
                "falsifiable_prediction": "HLA-DRA expression will track antigen presentation.",
                "evidence_references": ["stage3_HLA-DRA.json"],
                "biological_entities": {
                    "genes": ["HLA-DRA"],
                    "pathways": ["antigen presentation"],
                    "cell_types": ["pulmonary alveolar type 2 cell"],
                    "drugs": [],
                },
            }
        ]
    }

    assert validate_hypothesis_grounding(report, evidence) == []
