from __future__ import annotations

import json
from pathlib import Path

from src.agents.drug_target.subagents import prompts
from src.agents.drug_target.tools import save_hypothesis_report
from src.agents.drug_target.tools.evidence_loader import (
    load_evidence_files,
    validate_evidence_references,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
    assert "biological_entities.cell_types" in text
    assert "Do not claim that Census separately validated a lost state modifier" in text
    assert "must not appear in `evidence_references`" in text
    assert "cite Stage 1 pair files for Census evidence" in text
    assert "AT2" in text
    assert "Transitional AT2" in text
