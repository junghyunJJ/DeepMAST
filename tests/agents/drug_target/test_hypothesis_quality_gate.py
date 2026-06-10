from __future__ import annotations

import json
from pathlib import Path

from src.agents.drug_target.tools.hypothesis_schema import (
    REQUIRED_HYPOTHESIS_CATEGORIES,
    save_hypothesis_report,
    validate_hypothesis_report_quality,
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
            {"ligand": "FN1", "receptor": "CD4", "passed": True},
            {"ligand": "FN1", "receptor": "SDC2", "passed": True},
            {"ligand": "FN1", "receptor": "PLAUR", "passed": False},
        ]),
        encoding="utf-8",
    )
    for name in (
        "stage1_FN1--CD4.json",
        "stage1_FN1--SDC2.json",
        "stage1_FN1--PLAUR.json",
        "stage3_CD4.json",
        "stage3_FN1.json",
    ):
        (evidence_dir / name).write_text("{}", encoding="utf-8")
    return tmp_path


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


def _hypothesis(rank: int, category: str, title: str, refs: list[str], genes: list[str]) -> dict:
    return {
        "rank": rank,
        "title": title,
        "category": category,
        "gap_type": "none",
        "core_claim": f"{title} is testable in IPF biology.",
        "evidence_references": refs,
        "contrast_references": [],
        "biological_entities": {
            "genes": genes,
            "pathways": [],
            "cell_types": [],
            "drugs": [],
        },
        "falsifiable_prediction": "Measurable qualitative response change.",
        "validation_approach": "Run perturbation assay with matched controls.",
        "scores": {
            "evidence_coverage": 0.8,
            "specificity": 0.8,
            "novelty": 0.7,
            "actionability": 0.7,
            "composite": 0.75,
        },
    }


def _valid_report() -> dict:
    return {
        "schema_version": "hypothesis_report.v2",
        "disease": "IPF",
        "hypotheses_generated": 4,
        "hypotheses_retained": 4,
        "hypotheses": [
            _hypothesis(
                1,
                "Mechanism of Action",
                "FN1-CD4 mechanism",
                ["stage1_FN1--CD4.json", "stage3_FN1.json", "stage3_CD4.json"],
                ["FN1", "CD4"],
            ),
            _hypothesis(
                2,
                "Therapeutic Strategy",
                "FN1 actionability follow-up",
                ["stage1_FN1--SDC2.json", "stage3_FN1.json"],
                ["FN1", "SDC2"],
            ),
            _hypothesis(
                3,
                "Cross-Target Interaction",
                "FN1-CD4 cross target",
                ["stage1_FN1--CD4.json", "stage3_FN1.json", "stage3_CD4.json"],
                ["FN1", "CD4"],
            ),
            _hypothesis(
                4,
                "Novel Pathway",
                "FN1 matrix remodeling pathway",
                ["stage3_FN1.json", "stage3_CD4.json"],
                ["FN1", "CD4"],
            ),
        ],
        "gap_analysis": {},
    }


def _codes(result: dict) -> set[str]:
    return {err["code"] for err in result.get("errors", [])}


def _warning_codes(result: dict) -> set[str]:
    return {
        warning["code"]
        for warning in result.get("warnings", [])
        if isinstance(warning, dict) and "code" in warning
    }


def test_quality_gate_reports_missing_hypothesis_report(tmp_path: Path) -> None:
    _write_hypothesis_evidence(tmp_path)

    result = validate_hypothesis_report_quality(tmp_path)

    assert result["valid"] is False
    assert "HYPOTHESIS_REPORT_MISSING" in _codes(result)


def test_quality_gate_includes_last_rejection_when_report_missing(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    sidecar = data_dir / "evidence" / "hypothesis_report_last_rejection.json"
    sidecar.write_text(
        json.dumps({
            "saved": False,
            "stage": "save_hypothesis_report",
            "created_at": "2026-06-08T10:00:00+00:00",
            "errors": [
                "hypotheses[5] claims direct pair axis 'EZR--MUC1' without citing a matching passed Stage 1 pair file.",
            ],
            "hypothesis_grounding_violations": [
                "hypotheses[5] claims direct pair axis 'EZR--MUC1' without citing a matching passed Stage 1 pair file.",
            ],
        }),
        encoding="utf-8",
    )

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is False
    assert "HYPOTHESIS_REPORT_MISSING" in _codes(result)
    assert "HYPOTHESIS_LAST_SAVE_REJECTION" in _codes(result)
    rejection_errors = [
        err for err in result["errors"]
        if err["code"] == "HYPOTHESIS_LAST_SAVE_REJECTION"
    ]
    assert "EZR--MUC1" in rejection_errors[0]["details"]["errors"][0]


def test_quality_gate_sanitizes_reserved_keys_in_last_rejection_sidecar(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    sidecar = data_dir / "evidence" / "hypothesis_report_last_rejection.json"
    sidecar.write_text(
        json.dumps({
            "code": "SIDE_CODE",
            "message": "side message",
            "errors": ["sidecar rejection"],
        }),
        encoding="utf-8",
    )

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is False
    assert "HYPOTHESIS_REPORT_MISSING" in _codes(result)
    assert "HYPOTHESIS_LAST_SAVE_REJECTION" in _codes(result)
    rejection = [
        err for err in result["errors"]
        if err["code"] == "HYPOTHESIS_LAST_SAVE_REJECTION"
    ][0]
    assert rejection["details"]["errors"] == ["sidecar rejection"]
    assert rejection["details"]["sidecar_code"] == "SIDE_CODE"
    assert rejection["details"]["sidecar_message"] == "side message"


def test_quality_gate_reports_stale_hypothesis_report(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _valid_report()
    save_result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )
    assert save_result["saved"] is True
    hyp_path = data_dir / "evidence" / "hypothesis_report.json"
    run_started_at = hyp_path.stat().st_mtime + 10

    result = validate_hypothesis_report_quality(data_dir, run_started_at=run_started_at)

    assert result["valid"] is False
    assert "HYPOTHESIS_REPORT_STALE" in _codes(result)


def test_quality_gate_includes_last_rejection_when_report_stale(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    save_result = json.loads(
        save_hypothesis_report.invoke({
            "data_dir": str(data_dir),
            "report": _valid_report(),
        })
    )
    assert save_result["saved"] is True
    sidecar = data_dir / "evidence" / "hypothesis_report_last_rejection.json"
    sidecar.write_text(
        json.dumps({
            "saved": False,
            "stage": "save_hypothesis_report",
            "created_at": "2026-06-08T10:00:00+00:00",
            "errors": [
                "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING: hypotheses[3] missing available gene-level evidence references for FEATURED genes: ICAM1: ot_ICAM1.json, stage3_ICAM1.json",
            ],
        }),
        encoding="utf-8",
    )
    hyp_path = data_dir / "evidence" / "hypothesis_report.json"
    run_started_at = hyp_path.stat().st_mtime + 10

    result = validate_hypothesis_report_quality(data_dir, run_started_at=run_started_at)

    assert result["valid"] is False
    assert "HYPOTHESIS_REPORT_STALE" in _codes(result)
    assert "HYPOTHESIS_LAST_SAVE_REJECTION" in _codes(result)
    rejection_errors = [
        err for err in result["errors"]
        if err["code"] == "HYPOTHESIS_LAST_SAVE_REJECTION"
    ]
    assert (
        "ICAM1: ot_ICAM1.json, stage3_ICAM1.json"
        in rejection_errors[0]["details"]["errors"][0]
    )


def test_quality_gate_accepts_valid_report_with_all_required_categories(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    save_result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": _valid_report()})
    )
    assert save_result["saved"] is True

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is True
    assert result["hypothesis_count"] == 4
    assert set(result["category_coverage"]["present"]) == REQUIRED_HYPOTHESIS_CATEGORIES
    assert result["category_coverage"]["missing"] == []


def test_quality_gate_warns_on_empty_stage3_matched_drug_wording(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    evidence_dir = data_dir / "evidence"
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "CD47"}]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage3_CD47.json").write_text(
        json.dumps({"gene_symbol": "CD47", "chembl": {"matched_drugs": []}}),
        encoding="utf-8",
    )
    (evidence_dir / "ot_CD47.json").write_text(
        json.dumps({"known_drugs": [{"name": "MAGROLIMAB"}]}),
        encoding="utf-8",
    )
    report = _valid_report()
    report["hypotheses"] = [
        _hypothesis(
            1,
            "Mechanism of Action",
            "CD47 ChEMBL actionability hypothesis",
            ["stage3_CD47.json", "ot_CD47.json"],
            ["CD47"],
        ),
        _hypothesis(
            2,
            "Therapeutic Strategy",
            "CD47 therapeutic follow-up",
            ["stage3_CD47.json", "ot_CD47.json"],
            ["CD47"],
        ),
        _hypothesis(
            3,
            "Cross-Target Interaction",
            "CD47 cross-target follow-up",
            ["stage3_CD47.json", "ot_CD47.json"],
            ["CD47"],
        ),
        _hypothesis(
            4,
            "Novel Pathway",
            "CD47 novel pathway follow-up",
            ["stage3_CD47.json", "ot_CD47.json"],
            ["CD47"],
        ),
    ]
    report["hypotheses"][0]["core_claim"] = (
        "CD47 has Stage 3 ChEMBL drug evidence and OpenTargets known-drug support."
    )
    (evidence_dir / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is True, result
    assert "EMPTY_STAGE3_MATCHED_DRUGS_WORDING" in _warning_codes(result)


def test_quality_gate_warns_on_entity_gene_without_cited_support(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _valid_report()
    report["hypotheses"][1]["evidence_references"] = ["stage3_FN1.json"]
    report["hypotheses"][1]["biological_entities"]["genes"] = ["FN1", "SDC2"]
    (data_dir / "evidence" / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is True, result
    assert "BIOLOGICAL_ENTITY_GENE_WITHOUT_CITED_SUPPORT" in _warning_codes(result)


def test_quality_gate_warns_on_fibrosis_resolution_wording(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _valid_report()
    report["hypotheses"][3]["title"] = (
        "FN1 actionability follow-up candidate for fibrosis resolution"
    )
    report["hypotheses"][3]["core_claim"] = (
        "FN1 perturbation may change fibrosis resolution readouts."
    )
    report["hypotheses"][3]["validation_approach"] = (
        "Measure fibrosis resolution endpoints in matched perturbation assays."
    )
    (data_dir / "evidence" / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is True, result
    assert "FIBROSIS_RESOLUTION_WORDING" in _warning_codes(result)


def test_quality_gate_reports_missing_featured_gene_level_refs_in_stale_report(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _valid_report()
    report["hypotheses"][0]["evidence_references"] = [
        "stage1_FN1--CD4.json",
        "stage3_FN1.json",
    ]
    (data_dir / "evidence" / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is False
    assert "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING" in _codes(result)
    gene_ref_errors = [
        error
        for error in result["errors"]
        if error["code"] == "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING"
    ]
    assert any(
        "stage3_CD4.json" in item
        for error in gene_ref_errors
        for item in error["details"]["errors"]
    )


def test_quality_gate_reports_malformed_assessment_for_gene_ref_gate(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    (data_dir / "evidence" / "assessment_results.json").write_text(
        "{not-json",
        encoding="utf-8",
    )
    (data_dir / "evidence" / "hypothesis_report.json").write_text(
        json.dumps(_valid_report()),
        encoding="utf-8",
    )

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is False
    assert "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING" in _codes(result)
    gene_ref_errors = [
        error
        for error in result["errors"]
        if error["code"] == "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING"
    ]
    assert any(
        "assessment_results.json" in item
        for error in gene_ref_errors
        for item in error["details"]["errors"]
    )


def test_quality_gate_reports_non_list_stage3_candidates_for_gene_ref_gate(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    (data_dir / "evidence" / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": "ICAM1"}),
        encoding="utf-8",
    )
    (data_dir / "evidence" / "hypothesis_report.json").write_text(
        json.dumps(_valid_report()),
        encoding="utf-8",
    )

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is False
    assert "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING" in _codes(result)
    gene_ref_errors = [
        error
        for error in result["errors"]
        if error["code"] == "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING"
    ]
    assert any(
        "stage3_candidates" in item
        for error in gene_ref_errors
        for item in error["details"]["errors"]
    )


def test_quality_gate_rejects_missing_primary_epithelial_intrinsic_coverage(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    _add_intrinsic_stage1_evidence(data_dir)
    report = _valid_report()
    report["hypotheses"][0]["title"] = "AT2 epithelial FN1-CD4 mechanism"
    report["hypotheses"][0]["core_claim"] = (
        "AT2 epithelial FN1-CD4 biology is testable while intrinsic Stage 1 "
        "support is available."
    )
    report["hypotheses"][0]["biological_entities"]["cell_types"] = ["AT2 epithelial"]
    (data_dir / "evidence" / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is False
    assert "PRIMARY_EPITHELIAL_INTRINSIC_COVERAGE_MISSING" in _codes(result)


def test_quality_gate_rejects_missing_intrinsic_coverage_with_stale_stage1_pair_files(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    _add_intrinsic_stage1_evidence(data_dir)
    report = _valid_report()
    report["stage1_pair_files"] = ["stage1_FN1--CD4.json"]
    report["hypotheses"][0]["title"] = "AT2 epithelial FN1-CD4 mechanism"
    report["hypotheses"][0]["core_claim"] = (
        "AT2 epithelial FN1-CD4 biology is testable while intrinsic Stage 1 "
        "support is available on disk but uncited."
    )
    report["hypotheses"][0]["biological_entities"]["cell_types"] = ["AT2 epithelial"]
    (data_dir / "evidence" / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is False
    assert "PRIMARY_EPITHELIAL_INTRINSIC_COVERAGE_MISSING" in _codes(result)


def test_quality_gate_accepts_primary_epithelial_intrinsic_coverage(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    _add_intrinsic_stage1_evidence(data_dir)
    report = _valid_report()
    report["stage1_pair_files"] = ["stage1_ICAM1--MUC1.json"]
    hyp = report["hypotheses"][0]
    hyp["title"] = "Primary AT2 epithelial ICAM1-MUC1 mechanism"
    hyp["core_claim"] = (
        "ICAM1-MUC1 supports a primary AT2 epithelial follow-up mechanism."
    )
    hyp["evidence_references"] = [
        "stage1_ICAM1--MUC1.json",
        "stage3_CD4.json",
    ]
    hyp["biological_entities"]["genes"] = ["ICAM1", "MUC1", "CD4"]
    hyp["biological_entities"]["cell_types"] = ["AT2 epithelial"]
    hyp["validation_approach"] = "Test ICAM1-MUC1 perturbation in AT2 epithelial cells."
    save_result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )
    assert save_result["saved"] is True, save_result

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is True
    assert "PRIMARY_EPITHELIAL_INTRINSIC_COVERAGE_MISSING" not in _codes(result)


def test_quality_gate_rejects_missing_required_category(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _valid_report()
    report["hypotheses"][3]["category"] = "Mechanism of Action"
    save_result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )
    assert save_result["saved"] is True

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is False
    assert "MISSING_REQUIRED_CATEGORIES" in _codes(result)
    assert result["category_coverage"]["missing"] == ["Novel Pathway"]


def test_quality_gate_rejects_count_outside_four_to_six(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _valid_report()
    report["hypotheses"].append(
        _hypothesis(
            5,
            "Mechanism of Action",
            "extra mechanism 1",
            ["stage3_FN1.json"],
            ["FN1"],
        )
    )
    report["hypotheses"].append(
        _hypothesis(
            6,
            "Therapeutic Strategy",
            "extra therapeutic",
            ["stage3_CD4.json"],
            ["CD4"],
        )
    )
    report["hypotheses"].append(
        _hypothesis(
            7,
            "Novel Pathway",
            "extra novel",
            ["stage3_FN1.json"],
            ["FN1"],
        )
    )
    save_result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )
    assert save_result["saved"] is True

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is False
    assert "HYPOTHESIS_COUNT_OUT_OF_RANGE" in _codes(result)


def test_quality_gate_rejects_unverified_numeric_prediction(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _valid_report()
    report["hypotheses"][0]["falsifiable_prediction"] = "Expect a 40% reduction."
    save_result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )
    assert save_result["saved"] is False
    assert any("unverified numeric values" in error for error in save_result["errors"])

    # Existing/stale artifacts can still be audited by the quality gate even when
    # the normal save path would reject the same payload.
    (data_dir / "evidence" / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is False
    assert "UNVERIFIED_NUMERIC_PREDICTION" in _codes(result)


def test_quality_gate_surfaces_schema_reference_and_topn_errors(tmp_path: Path) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _valid_report()
    del report["hypotheses"][0]["scores"]["composite"]
    (data_dir / "evidence" / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    result = validate_hypothesis_report_quality(data_dir)

    assert result["valid"] is False
    assert "SCHEMA_VALIDATION_FAILED" in _codes(result)
