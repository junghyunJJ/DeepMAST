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
