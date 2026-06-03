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
                ["stage1_FN1--CD4.json", "stage3_CD4.json"],
                ["FN1", "CD4"],
            ),
            _hypothesis(
                2,
                "Therapeutic Strategy",
                "FN1 therapeutic strategy",
                ["stage1_FN1--SDC2.json", "stage3_FN1.json"],
                ["FN1", "SDC2"],
            ),
            _hypothesis(
                3,
                "Cross-Target Interaction",
                "FN1-CD4 cross target",
                ["stage1_FN1--CD4.json"],
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


def test_quality_gate_reports_missing_hypothesis_report(tmp_path: Path) -> None:
    _write_hypothesis_evidence(tmp_path)

    result = validate_hypothesis_report_quality(tmp_path)

    assert result["valid"] is False
    assert "HYPOTHESIS_REPORT_MISSING" in _codes(result)


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
    assert save_result["saved"] is True

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
