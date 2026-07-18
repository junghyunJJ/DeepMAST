from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.drug_target.ollama_hypothesis_cards import (
    build_ollama_hypothesis_report,
)
from src.agents.drug_target.tools import (
    save_evidence,
    save_hypothesis_report,
    validate_evidence_references,
)
from src.agents.drug_target.tools.hypothesis_schema import (
    canonicalize_hypothesis_report,
    validate_canonical_hypothesis_report,
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


def test_save_hypothesis_report_redirects_virtual_root_to_env_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("DRUG_TARGET_DATA_DIR", str(workspace))

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": "/", "report": {"hypotheses": []}})
    )

    assert result["path"] == str(workspace / "evidence" / "hypothesis_report.json")
    assert (workspace / "evidence").exists()


def _add_intrinsic_stage1_evidence(data_dir: Path) -> None:
    evidence_dir = data_dir / "evidence"
    filter_path = evidence_dir / "stage1_filter_results.json"
    rows = json.loads(filter_path.read_text(encoding="utf-8"))
    rows.insert(0, {"ligand": "ICAM1", "receptor": "MUC1", "passed": True})
    filter_path.write_text(json.dumps(rows), encoding="utf-8")
    (evidence_dir / "stage1_ICAM1--MUC1.json").write_text(
        json.dumps({
            "pair_id": "ICAM1--MUC1",
            "status": "PASS",
            "census_validation": {
                "risk_ratio": 17.863,
                "p_value": 0.0,
                "requested_cell_type": "AT2",
                "resolved_cell_type": "pulmonary alveolar type 2 cell",
                "target_vs_rest": {
                    "gene_a": {"direction": "enriched", "risk_ratio": 2.0},
                    "gene_b": {"direction": "enriched", "risk_ratio": 2.0},
                    "coexpression": {"direction": "enriched", "risk_ratio": 2.0},
                },
            },
        }),
        encoding="utf-8",
    )


def _write_malignant_intrinsic_evidence(tmp_path: Path) -> Path:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "EGF"}, {"gene": "ERBB2"}]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_filter_results.json").write_text(
        json.dumps([{"ligand": "EGF", "receptor": "ERBB2", "passed": True}]),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_EGF--ERBB2.json").write_text(
        json.dumps({
            "pair_id": "EGF--ERBB2",
            "status": "PASS",
            "census_validation": {
                "risk_ratio": 6.25,
                "p_value": 0.0,
                "requested_cell_type": "Prolif Invasive Tumor",
                "resolved_cell_type": "malignant cell",
                "target_vs_rest": {
                    "gene_a": {"direction": "enriched", "risk_ratio": 2.0},
                    "gene_b": {"direction": "enriched", "risk_ratio": 2.0},
                    "coexpression": {"direction": "enriched", "risk_ratio": 6.25},
                },
            },
            "stage1_filter": {
                "passed": True,
                "string_combined": 0.99,
                "census_coexpr_pvalue": 0.0,
                "census_gene_a_pvalue": 0.0,
                "census_gene_b_pvalue": 0.0,
            },
        }),
        encoding="utf-8",
    )
    (evidence_dir / "stage3_EGF.json").write_text(
        json.dumps({"gene_symbol": "EGF"}),
        encoding="utf-8",
    )
    (evidence_dir / "stage3_ERBB2.json").write_text(
        json.dumps({"gene_symbol": "ERBB2"}),
        encoding="utf-8",
    )
    (evidence_dir / "celltype_resolution.json").write_text(
        json.dumps({
            "interest_celltypes": ["Prolif Invasive Tumor"],
            "primary_input_celltype": "Prolif Invasive Tumor",
            "primary_resolved_celltype": "malignant cell",
            "primary_match_mode": "semantic_proxy",
            "matches": [
                {
                    "input_celltype": "Prolif Invasive Tumor",
                    "matched_celltype": "malignant cell",
                    "match_mode": "semantic_proxy",
                }
            ],
        }),
        encoding="utf-8",
    )
    return tmp_path


def _write_ollama_enrichment_evidence(tmp_path: Path) -> Path:
    data_dir = _write_malignant_intrinsic_evidence(tmp_path)
    evidence_dir = data_dir / "evidence"
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({
            "stage3_candidates": [
                {"gene": "EGF"},
                {"gene": "ERBB2"},
                {"gene": "TP53"},
                {"gene": "KRAS"},
            ]
        }),
        encoding="utf-8",
    )
    for gene in ("TP53", "KRAS"):
        (evidence_dir / f"stage3_{gene}.json").write_text(
            json.dumps({"gene_symbol": gene}),
            encoding="utf-8",
        )
    return data_dir


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


def test_validate_canonical_hypothesis_report_is_pure(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _clone_report()
    canonical, errors, _ = canonicalize_hypothesis_report(
        report,
        data_dir / "evidence",
        legacy_compat=False,
    )

    assert canonical is not None
    assert errors == []
    assert validate_canonical_hypothesis_report(
        canonical,
        data_dir / "evidence",
        min_hypotheses=0,
        max_hypotheses=0,
    ) == []
    assert not (data_dir / "evidence" / "hypothesis_report.json").exists()


def _write_featured_gene_reference_evidence(
    tmp_path: Path,
    *,
    featured: list[str],
    pair: tuple[str, str],
    gene_files: set[str],
) -> Path:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    ligand, receptor = pair
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": gene} for gene in featured]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_filter_results.json").write_text(
        json.dumps([{"ligand": ligand, "receptor": receptor, "passed": True}]),
        encoding="utf-8",
    )
    (evidence_dir / f"stage1_{ligand}--{receptor}.json").write_text(
        json.dumps({
            "pair_id": f"{ligand}--{receptor}",
            "status": "PASS",
            "census_validation": {
                "requested_cell_type": "pulmonary alveolar type 2 cell",
                "resolved_cell_type": "pulmonary alveolar type 2 cell",
                "target_vs_rest": {
                    "gene_a": {"direction": "enriched", "risk_ratio": 2.0},
                    "gene_b": {"direction": "enriched", "risk_ratio": 2.0},
                    "coexpression": {"direction": "enriched", "risk_ratio": 4.0},
                },
            },
            "stage1_filter": {
                "passed": True,
                "string_combined": 0.99,
                "census_coexpr_pvalue": 0.0,
                "census_gene_a_pvalue": 0.0,
                "census_gene_b_pvalue": 0.0,
            },
        }),
        encoding="utf-8",
    )
    for filename in sorted(gene_files):
        (evidence_dir / filename).write_text(
            json.dumps({"gene_symbol": filename.split("_", 1)[1].split(".", 1)[0]}),
            encoding="utf-8",
        )
    return tmp_path


def _write_semantic_warning_evidence(
    tmp_path: Path,
    *,
    featured: list[str],
    pairs: list[tuple[str, str]],
    gene_files: dict[str, dict],
) -> Path:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": gene} for gene in featured]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_filter_results.json").write_text(
        json.dumps([
            {"ligand": ligand, "receptor": receptor, "passed": True}
            for ligand, receptor in pairs
        ]),
        encoding="utf-8",
    )
    for ligand, receptor in pairs:
        (evidence_dir / f"stage1_{ligand}--{receptor}.json").write_text(
            json.dumps({
                "pair_id": f"{ligand}--{receptor}",
                "status": "PASS",
                "stage1_filter": {"passed": True},
            }),
            encoding="utf-8",
        )
    for filename, payload in sorted(gene_files.items()):
        (evidence_dir / filename).write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def _pair_report(
    *,
    title: str,
    core_claim: str,
    refs: list[str],
    genes: list[str],
    validation: str,
) -> dict:
    return {
        "schema_version": "hypothesis_report.v2",
        "disease": "IPF",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": title,
                "category": "Mechanism of Action",
                "gap_type": "none",
                "core_claim": core_claim,
                "evidence_references": refs,
                "contrast_references": [],
                "biological_entities": {
                    "genes": genes,
                    "pathways": ["cell adhesion"],
                    "cell_types": ["pulmonary alveolar type 2 cell"],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "Test whether the cited genes change epithelial readouts."
                ),
                "validation_approach": validation,
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
            "total_evidence_files": 0,
            "referenced_files": 0,
            "orphan_files": [],
        },
    }


def test_failed_hypothesis_save_writes_rejection_sidecar(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    bad_report = _clone_report()
    bad_report["hypotheses"][0]["evidence_references"] = [
        "stage1_FN1--CD4.json",
        "stage3_FN1.json",
    ]

    result = json.loads(
        save_hypothesis_report.invoke({
            "data_dir": str(data_dir),
            "report": bad_report,
        })
    )

    assert result["saved"] is False
    sidecar = data_dir / "evidence" / "hypothesis_report_last_rejection.json"
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["saved"] is False
    assert payload["stage"] == "save_hypothesis_report"
    assert payload["errors"] == result["errors"]
    assert payload["topn_coverage"] == result["topn_coverage"]
    assert "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING" in payload["errors"][0]
    assert payload["created_at"]


def test_successful_hypothesis_save_removes_rejection_sidecar(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    sidecar = data_dir / "evidence" / "hypothesis_report_last_rejection.json"
    sidecar.write_text(
        json.dumps({
            "saved": False,
            "stage": "save_hypothesis_report",
            "errors": ["old rejection"],
            "created_at": "2026-06-08T00:00:00Z",
        }),
        encoding="utf-8",
    )

    result = json.loads(
        save_hypothesis_report.invoke({
            "data_dir": str(data_dir),
            "report": _clone_report(),
        })
    )

    assert result["saved"] is True
    assert not sidecar.exists()


def test_hypothesis_rejection_sidecar_write_failure_preserves_rejection_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    bad_report = _clone_report()
    bad_report["hypotheses"][0]["evidence_references"] = [
        "stage1_FN1--CD4.json",
        "stage3_FN1.json",
    ]
    sidecar = data_dir / "evidence" / "hypothesis_report_last_rejection.json"
    original_write_text = Path.write_text

    def fail_sidecar_write(path: Path, *args, **kwargs):
        if path.name == "hypothesis_report_last_rejection.json":
            raise OSError("sidecar write failed")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_sidecar_write)

    result = json.loads(
        save_hypothesis_report.invoke({
            "data_dir": str(data_dir),
            "report": bad_report,
        })
    )

    assert result["saved"] is False
    assert "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING" in result["errors"][0]
    assert not sidecar.exists()


def test_hypothesis_rejection_sidecar_cleanup_failure_preserves_success_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    sidecar = data_dir / "evidence" / "hypothesis_report_last_rejection.json"
    sidecar.write_text(
        json.dumps({
            "saved": False,
            "stage": "save_hypothesis_report",
            "errors": ["old rejection"],
            "created_at": "2026-06-08T00:00:00Z",
        }),
        encoding="utf-8",
    )
    original_unlink = Path.unlink

    def fail_sidecar_unlink(path: Path, *args, **kwargs):
        if path.name == "hypothesis_report_last_rejection.json":
            raise OSError("sidecar cleanup failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_sidecar_unlink)

    result = json.loads(
        save_hypothesis_report.invoke({
            "data_dir": str(data_dir),
            "report": _clone_report(),
        })
    )

    assert result["saved"] is True
    assert (data_dir / "evidence" / "hypothesis_report.json").exists()
    assert sidecar.exists()


def test_save_hypothesis_report_rejects_missing_featured_gene_level_refs_when_files_exist(
    tmp_path: Path,
) -> None:
    data_dir = _write_featured_gene_reference_evidence(
        tmp_path,
        featured=["ICAM1", "MUC1"],
        pair=("ICAM1", "MUC1"),
        gene_files={
            "ot_ICAM1.json",
            "ot_MUC1.json",
            "stage3_ICAM1.json",
            "stage3_MUC1.json",
        },
    )
    report = _pair_report(
        title="ICAM1-MUC1 coexpression nominates epithelial follow-up axis",
        core_claim=(
            "ICAM1-MUC1 is an AT2 epithelial follow-up candidate with Stage 3 "
            "support but missing OpenTargets citations."
        ),
        refs=[
            "stage1_ICAM1--MUC1.json",
            "stage3_ICAM1.json",
            "stage3_MUC1.json",
        ],
        genes=["ICAM1", "MUC1"],
        validation="Test ICAM1 and MUC1 in pulmonary alveolar type 2 cell models.",
    )

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING" in error
        for error in result["errors"]
    )
    assert any(
        "ot_ICAM1.json" in error and "ot_MUC1.json" in error
        for error in result["errors"]
    )
    assert not (data_dir / "evidence" / "hypothesis_report.json").exists()


def test_save_hypothesis_report_accepts_asymmetric_pair_with_supported_featured_gene_refs(
    tmp_path: Path,
) -> None:
    data_dir = _write_featured_gene_reference_evidence(
        tmp_path,
        featured=["ICAM1"],
        pair=("ICAM1", "EZR"),
        gene_files={
            "ot_ICAM1.json",
            "stage3_ICAM1.json",
            "ot_EZR.json",
        },
    )
    report = _pair_report(
        title=(
            "ICAM1-EZR coexpression nominates an ICAM1-anchored epithelial "
            "follow-up axis"
        ),
        core_claim=(
            "ICAM1 is the FEATURED gene with cited gene-level support, while EZR "
            "is a Stage 1 coexpression-context partner."
        ),
        refs=[
            "stage1_ICAM1--EZR.json",
            "ot_ICAM1.json",
            "stage3_ICAM1.json",
        ],
        genes=["ICAM1", "EZR"],
        validation="Test ICAM1 and EZR in pulmonary alveolar type 2 cell models.",
    )

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result
    saved = json.loads((data_dir / "evidence" / "hypothesis_report.json").read_text())
    refs = saved["hypotheses"][0]["evidence_references"]
    assert refs == [
        "stage1_ICAM1--EZR.json",
        "ot_ICAM1.json",
        "stage3_ICAM1.json",
    ]
    assert "ot_EZR.json" not in refs


def test_save_hypothesis_report_ignores_text_mentioned_featured_gene_absent_from_entities(
    tmp_path: Path,
) -> None:
    data_dir = _write_featured_gene_reference_evidence(
        tmp_path,
        featured=["ICAM1"],
        pair=("ICAM1", "EZR"),
        gene_files={
            "ot_ICAM1.json",
            "stage3_ICAM1.json",
        },
    )
    report = _pair_report(
        title="EZR follow-up keeps ICAM1 as background context only",
        core_claim=(
            "EZR is the nominated target; ICAM1 is mentioned only as upstream "
            "context and is not part of the hypothesis gene entity list."
        ),
        refs=["stage1_ICAM1--EZR.json"],
        genes=["EZR"],
        validation=(
            "Test the EZR-centered readout in pulmonary alveolar type 2 cell models."
        ),
    )
    icam1_hypothesis = json.loads(json.dumps(report["hypotheses"][0]))
    icam1_hypothesis.update({
        "rank": 2,
        "title": "ICAM1 cited featured coverage hypothesis",
        "core_claim": "ICAM1 has cited gene-level support for follow-up.",
        "evidence_references": [
            "stage1_ICAM1--EZR.json",
            "ot_ICAM1.json",
            "stage3_ICAM1.json",
        ],
        "biological_entities": {
            "genes": ["ICAM1"],
            "pathways": ["cell adhesion"],
            "cell_types": ["pulmonary alveolar type 2 cell"],
            "drugs": [],
        },
        "validation_approach": (
            "Test ICAM1 in pulmonary alveolar type 2 cell models."
        ),
    })
    report["hypotheses"].append(icam1_hypothesis)
    report["hypotheses_generated"] = 2
    report["hypotheses_retained"] = 2

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result


def test_save_hypothesis_report_treats_hyphenated_pair_as_featured_gene_mentions(
    tmp_path: Path,
) -> None:
    data_dir = _write_featured_gene_reference_evidence(
        tmp_path,
        featured=["ICAM1", "MUC1"],
        pair=("ICAM1", "MUC1"),
        gene_files={
            "ot_ICAM1.json",
            "ot_MUC1.json",
            "stage3_ICAM1.json",
            "stage3_MUC1.json",
        },
    )
    report = _pair_report(
        title="ICAM1-MUC1 coexpression nominates epithelial follow-up axis",
        core_claim=(
            "The ICAM1-MUC1 pair is an AT2 epithelial follow-up candidate with "
            "Stage 3 support but omitted OpenTargets citations."
        ),
        refs=[
            "stage1_ICAM1--MUC1.json",
            "stage3_ICAM1.json",
            "stage3_MUC1.json",
        ],
        genes=["ICAM1", "MUC1"],
        validation="Test the paired axis in pulmonary alveolar type 2 cell models.",
    )

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING" in error
        for error in result["errors"]
    )
    assert any(
        "ot_ICAM1.json" in error and "ot_MUC1.json" in error
        for error in result["errors"]
    )
    assert not (data_dir / "evidence" / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_malformed_assessment_for_gene_ref_gate(
    tmp_path: Path,
) -> None:
    data_dir = _write_featured_gene_reference_evidence(
        tmp_path,
        featured=["ICAM1"],
        pair=("ICAM1", "MUC1"),
        gene_files={
            "ot_ICAM1.json",
            "stage3_ICAM1.json",
        },
    )
    (data_dir / "evidence" / "assessment_results.json").write_text(
        "{not-json",
        encoding="utf-8",
    )
    report = _pair_report(
        title="ICAM1 cited featured coverage hypothesis",
        core_claim="ICAM1 has cited gene-level support for follow-up.",
        refs=[
            "stage1_ICAM1--MUC1.json",
            "ot_ICAM1.json",
            "stage3_ICAM1.json",
        ],
        genes=["ICAM1"],
        validation="Test ICAM1 in pulmonary alveolar type 2 cell models.",
    )

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING" in error
        for error in result["errors"]
    )
    assert any("assessment_results.json" in error for error in result["errors"])
    assert not (data_dir / "evidence" / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_non_list_stage3_candidates_for_gene_ref_gate(
    tmp_path: Path,
) -> None:
    data_dir = _write_featured_gene_reference_evidence(
        tmp_path,
        featured=["ICAM1"],
        pair=("ICAM1", "MUC1"),
        gene_files={
            "ot_ICAM1.json",
            "stage3_ICAM1.json",
        },
    )
    (data_dir / "evidence" / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": "ICAM1"}),
        encoding="utf-8",
    )
    report = _pair_report(
        title="ICAM1 cited featured coverage hypothesis",
        core_claim="ICAM1 has cited gene-level support for follow-up.",
        refs=[
            "stage1_ICAM1--MUC1.json",
            "ot_ICAM1.json",
            "stage3_ICAM1.json",
        ],
        genes=["ICAM1"],
        validation="Test ICAM1 in pulmonary alveolar type 2 cell models.",
    )

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is False
    assert any(
        "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING" in error
        for error in result["errors"]
    )
    assert any("stage3_candidates" in error for error in result["errors"])
    assert not (data_dir / "evidence" / "hypothesis_report.json").exists()


def test_save_hypothesis_report_rejects_missing_primary_epithelial_intrinsic_coverage(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    _add_intrinsic_stage1_evidence(data_dir)
    report = _clone_report()
    hyp = report["hypotheses"][0]
    hyp["title"] = "AT2 epithelial CD4 contrast hypothesis"
    hyp["core_claim"] = (
        "AT2 epithelial CD4 biology is testable, but the intrinsic Stage 1 "
        "evidence is not cited."
    )
    hyp["biological_entities"]["cell_types"] = ["AT2 epithelial"]

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is False
    assert "PRIMARY_EPITHELIAL_INTRINSIC_COVERAGE_MISSING" in result["errors"]
    assert not (data_dir / "evidence" / "hypothesis_report.json").exists()


def test_save_hypothesis_report_warns_empty_stage3_matched_drugs_wording(
    tmp_path: Path,
) -> None:
    data_dir = _write_semantic_warning_evidence(
        tmp_path,
        featured=["CD47"],
        pairs=[("CD47", "FN1")],
        gene_files={
            "ot_CD47.json": {
                "gene_symbol": "CD47",
                "known_drugs": [{"drug_name": "magrolimab"}],
            },
            "stage3_CD47.json": {"gene_symbol": "CD47", "matched_drugs": []},
        },
    )
    report = _pair_report(
        title="CD47-FN1 axis nominates a CD47-anchored macrophage follow-up",
        core_claim=(
            "CD47 has Stage 3 ChEMBL drug and matched-drug support for IPF "
            "follow-up."
        ),
        refs=["stage1_CD47--FN1.json", "ot_CD47.json", "stage3_CD47.json"],
        genes=["CD47", "FN1"],
        validation="Test CD47 perturbation in macrophage-fibroblast coculture.",
    )

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result
    assert any(
        diagnostic.get("code") == "EMPTY_STAGE3_MATCHED_DRUGS_WORDING"
        and diagnostic.get("hypothesis_index") == 0
        and diagnostic.get("gene") == "CD47"
        for diagnostic in result["diagnostics"]
    )


def test_save_hypothesis_report_warns_context_partner_without_cited_support(
    tmp_path: Path,
) -> None:
    data_dir = _write_semantic_warning_evidence(
        tmp_path,
        featured=["FN1"],
        pairs=[("FN1", "CD4")],
        gene_files={
            "ot_FN1.json": {"gene_symbol": "FN1"},
            "stage3_FN1.json": {"gene_symbol": "FN1", "matched_drugs": []},
        },
    )
    report = _pair_report(
        title="FN1-anchored epithelial matrix follow-up",
        core_claim=(
            "FN1 is supported by cited evidence, while SDC2 is included as a "
            "biological entity."
        ),
        refs=["stage1_FN1--CD4.json", "ot_FN1.json", "stage3_FN1.json"],
        genes=["FN1", "SDC2"],
        validation="Test FN1 perturbation in pulmonary alveolar type 2 cell models.",
    )

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result
    assert any(
        diagnostic.get("code") == "BIOLOGICAL_ENTITY_GENE_WITHOUT_CITED_SUPPORT"
        and diagnostic.get("hypothesis_index") == 0
        and diagnostic.get("gene") == "SDC2"
        for diagnostic in result["diagnostics"]
    )


def test_save_hypothesis_report_warns_fibrosis_resolution_wording(
    tmp_path: Path,
) -> None:
    data_dir = _write_semantic_warning_evidence(
        tmp_path,
        featured=["FN1"],
        pairs=[("FN1", "CD4")],
        gene_files={
            "ot_FN1.json": {"gene_symbol": "FN1"},
            "stage3_FN1.json": {"gene_symbol": "FN1", "matched_drugs": []},
        },
    )
    report = _pair_report(
        title="FN1 axis for fibrosis resolution readouts",
        core_claim="FN1 has cited evidence for matrix follow-up.",
        refs=["stage1_FN1--CD4.json", "ot_FN1.json", "stage3_FN1.json"],
        genes=["FN1", "CD4"],
        validation="Test FN1 perturbation in pulmonary alveolar type 2 cell models.",
    )

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result
    assert any(
        diagnostic.get("code") == "FIBROSIS_RESOLUTION_WORDING"
        and diagnostic.get("hypothesis_index") == 0
        for diagnostic in result["diagnostics"]
    )


def test_save_hypothesis_report_rejects_missing_intrinsic_coverage_with_stale_stage1_pair_files(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    _add_intrinsic_stage1_evidence(data_dir)
    report = _clone_report()
    report["stage1_pair_files"] = ["stage1_FN1--CD4.json"]
    hyp = report["hypotheses"][0]
    hyp["title"] = "AT2 epithelial CD4 contrast hypothesis"
    hyp["core_claim"] = (
        "AT2 epithelial CD4 biology is testable, but the intrinsic Stage 1 "
        "evidence available on disk is not cited."
    )
    hyp["biological_entities"]["cell_types"] = ["AT2 epithelial"]

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is False
    assert "PRIMARY_EPITHELIAL_INTRINSIC_COVERAGE_MISSING" in result["errors"]
    assert not (data_dir / "evidence" / "hypothesis_report.json").exists()


def test_save_hypothesis_report_accepts_primary_interest_cell_intrinsic_coverage(
    tmp_path: Path,
) -> None:
    data_dir = _write_malignant_intrinsic_evidence(tmp_path)
    report = _clone_report()
    report["disease"] = "breast cancer"
    report["stage1_pair_files"] = ["stage1_EGF--ERBB2.json"]
    hyp = report["hypotheses"][0]
    hyp["title"] = "Primary EGF-ERBB2 intrinsic hypothesis"
    hyp["core_claim"] = (
        "EGF-ERBB2 supports a primary interest-cell intrinsic follow-up mechanism "
        "in resolved malignant cells."
    )
    hyp["evidence_references"] = [
        "stage1_EGF--ERBB2.json",
        "stage3_EGF.json",
        "stage3_ERBB2.json",
    ]
    hyp["biological_entities"]["genes"] = ["EGF", "ERBB2"]
    hyp["biological_entities"]["cell_types"] = ["malignant cells"]
    hyp["validation_approach"] = (
        "Test EGF-ERBB2 perturbation in malignant cells breast-cancer models."
    )

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result


def test_save_hypothesis_report_autofixes_intrinsic_coverage_interest_cell_anchor(
    tmp_path: Path,
) -> None:
    data_dir = _write_malignant_intrinsic_evidence(tmp_path)
    report = _clone_report()
    report["disease"] = "breast cancer"
    report["stage1_pair_files"] = ["stage1_EGF--ERBB2.json"]
    hyp = report["hypotheses"][0]
    hyp["title"] = "Primary EGF-ERBB2 intrinsic hypothesis"
    hyp["core_claim"] = (
        "EGF-ERBB2 supports a primary intrinsic follow-up mechanism in the "
        "disease context."
    )
    hyp["evidence_references"] = [
        "stage1_EGF--ERBB2.json",
        "stage3_EGF.json",
        "stage3_ERBB2.json",
    ]
    hyp["biological_entities"]["genes"] = ["EGF", "ERBB2"]
    hyp["biological_entities"]["cell_types"] = []
    hyp["validation_approach"] = "Test EGF-ERBB2 perturbation in disease models."

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result
    assert any(
        diagnostic.get("code") == "INTEREST_CELL_ANCHOR_AUTOFIX"
        and diagnostic.get("anchor") == "malignant cell"
        for diagnostic in result["diagnostics"]
    )
    saved = json.loads(
        (data_dir / "evidence" / "hypothesis_report.json").read_text(
            encoding="utf-8"
        )
    )
    saved_hyp = saved["hypotheses"][0]
    assert "malignant cell" in saved_hyp["biological_entities"]["cell_types"]
    assert "malignant cell" in saved_hyp["validation_approach"]


def test_save_hypothesis_report_accepts_primary_epithelial_intrinsic_coverage(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    _add_intrinsic_stage1_evidence(data_dir)
    report = _clone_report()
    report["stage1_pair_files"] = ["stage1_ICAM1--MUC1.json"]
    hyp = report["hypotheses"][0]
    hyp["title"] = "Primary AT2 epithelial ICAM1-MUC1 hypothesis"
    hyp["core_claim"] = (
        "ICAM1-MUC1 supports a primary AT2 epithelial follow-up mechanism."
    )
    hyp["evidence_references"] = [
        "stage3_CD4.json",
        "stage3_FN1.json",
        "stage1_FN1--CD4.json",
        "stage1_ICAM1--MUC1.json",
    ]
    hyp["biological_entities"]["genes"] = ["ICAM1", "MUC1", "CD4", "FN1"]
    hyp["biological_entities"]["cell_types"] = ["AT2 epithelial"]
    hyp["validation_approach"] = "Test ICAM1-MUC1 perturbation in AT2 epithelial cells."

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result


def test_save_hypothesis_report_keeps_unmarked_report_compatible_and_canonicalizes_labels_and_refs(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _strict_report()
    assert "interpretation_note" not in report["hypotheses"][0]

    result = json.loads(
        save_hypothesis_report.invoke(
            {"data_dir": str(data_dir), "report": report}
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


def test_save_hypothesis_report_rejects_marked_ollama_enrichment(
    tmp_path: Path,
) -> None:
    data_dir = _write_ollama_enrichment_evidence(tmp_path)
    report = build_ollama_hypothesis_report(data_dir, {})
    report["hypotheses"][0]["interpretation_note"] = (
        "This follow-up proves a causal mechanism."
    )

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is False
    assert "hypotheses[0].ollama_enrichment:CONSTRAINT_UNSAFE_CLAIM" in result["errors"]
    assert not (data_dir / "evidence" / "hypothesis_report.json").exists()


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


def test_save_hypothesis_report_allows_negated_pair_axis_wording(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _clone_report()
    hyp = report["hypotheses"][0]
    hyp["title"] = "FN1 and PLAUR gene-level follow-up context"
    hyp["core_claim"] = (
        "FN1 and PLAUR are not an L-R axis; they are tracked as separate "
        "gene-level context. The retained mechanism is grounded in FN1 Stage 3 "
        "evidence."
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


def test_save_hypothesis_report_keeps_numeric_prediction_check_after_other_gates(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _clone_report()
    report["hypotheses"][0]["evidence_references"] = ["stage3_missing.json"]
    report["hypotheses"][0]["falsifiable_prediction"] = "Expect a 40% reduction."

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is False
    assert any("not in evidence/ directory" in error for error in result["errors"])
    assert not any("unverified numeric values" in error for error in result["errors"])


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


def test_celltype_context_detects_legacy_at2_branch(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "celltype_resolution.json").write_text(
        json.dumps(
            {
                "interest_celltypes": ["AT2", "Transitional AT2"],
                "primary_resolved_celltype": "pulmonary alveolar type 2 cell",
                "matches": [
                    {
                        "input_celltype": "AT2",
                        "matched_celltype": "pulmonary alveolar type 2 cell",
                        "match_mode": "alias",
                    },
                    {
                        "input_celltype": "Transitional AT2",
                        "matched_celltype": "pulmonary alveolar type 2 cell",
                        "match_mode": "state_stripped_alias",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    from src.agents.drug_target.tools.hypothesis_schema import (
        _celltype_resolution_context,
    )

    context = _celltype_resolution_context(evidence_dir)

    assert context["branch"] == "legacy_at2"
    assert context["legacy_at2"] is True
    assert context["semantic_proxy"] is False
    assert "pulmonary alveolar type 2 cell" in context["anchor_tokens"]


def test_celltype_context_detects_generic_epithelial_legacy_branch(
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "celltype_resolution.json").write_text(
        json.dumps({"interest_celltypes": ["Epithelial"]}),
        encoding="utf-8",
    )

    from src.agents.drug_target.tools.hypothesis_schema import (
        _celltype_resolution_context,
    )

    context = _celltype_resolution_context(evidence_dir)

    assert context["branch"] == "legacy_at2"
    assert context["legacy_at2"] is True
    assert "epithelial" in context["anchor_tokens"]


def test_celltype_context_detects_semantic_proxy_branch(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "celltype_resolution.json").write_text(
        json.dumps(
            {
                "interest_celltypes": ["Prolif Invasive Tumor"],
                "primary_input_celltype": "Prolif Invasive Tumor",
                "primary_resolved_celltype": "malignant cell",
                "matches": [
                    {
                        "input_celltype": "Prolif Invasive Tumor",
                        "matched_celltype": "malignant cell",
                        "match_mode": "semantic_proxy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    from src.agents.drug_target.tools.hypothesis_schema import (
        _celltype_resolution_context,
    )

    context = _celltype_resolution_context(evidence_dir)

    assert context["branch"] == "semantic_proxy"
    assert context["legacy_at2"] is False
    assert context["semantic_proxy"] is True
    assert "malignant cell" in context["anchor_tokens"]
    assert "prolif invasive tumor" in context["anchor_tokens"]
