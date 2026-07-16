from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.drug_target.hybrid_report_sections import (
    REPORT_SECTIONS_FILENAME,
    canonicalize_report_sections,
)
from src.agents.drug_target.tools.hypothesis_schema import (
    canonicalize_hypothesis_report,
    validate_canonical_hypothesis_report,
)


def _write_evidence(tmp_path: Path) -> Path:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "CD4"}, {"gene": "FN1"}]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_filter_results.json").write_text(
        json.dumps(
            [
                {"ligand": "FN1", "receptor": "CD4", "passed": True},
                {"ligand": "FN1", "receptor": "SDC2", "passed": True},
            ]
        ),
        encoding="utf-8",
    )
    for filename in (
        "stage1_FN1--CD4.json",
        "stage1_FN1--SDC2.json",
        "stage3_CD4.json",
        "stage3_FN1.json",
    ):
        (evidence_dir / filename).write_text("{}", encoding="utf-8")
    return evidence_dir


def _hypothesis(
    rank: int,
    category: str,
    title: str,
    refs: list[str],
    genes: list[str],
) -> dict:
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
        "falsifiable_prediction": "Measure a qualitative response change.",
        "validation_approach": "Run a perturbation assay with matched controls.",
        "scores": {
            "evidence_coverage": 0.8,
            "specificity": 0.8,
            "novelty": 0.7,
            "actionability": 0.7,
            "composite": 0.75,
        },
    }


def _hypothesis_report() -> dict:
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
                "FN1-CD4 cross-target follow-up",
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


def _payload() -> dict:
    return {
        "schema_version": "hybrid_report_sections/v1",
        "hypothesis_report": _hypothesis_report(),
        "pipeline_recommendations": [
            {
                "text": (
                    "Prioritize orthogonal validation of FN1 before advancing target "
                    "selection."
                ),
                "supporting_sources": ["evidence/assessment_results.json"],
            },
            {
                "text": "Evaluate CD4 and FN1 signals in future mechanistic assays.",
                "supporting_sources": ["evidence/stage3_CD4.json"],
            },
        ],
    }


def _source_paths() -> set[str]:
    return {
        "evidence/assessment_results.json",
        "evidence/stage1_FN1--CD4.json",
        "evidence/stage1_FN1--SDC2.json",
        "evidence/stage3_CD4.json",
        "evidence/stage3_FN1.json",
    }


def _report_data() -> dict:
    return {
        "candidates": [
            {"gene": "CD4", "drugs": []},
            {"gene": "FN1", "drugs": []},
        ]
    }


def test_validate_canonical_hypothesis_report_accepts_current_contract_without_write(
    tmp_path: Path,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    canonical, errors, _ = canonicalize_hypothesis_report(
        _hypothesis_report(),
        evidence_dir,
        legacy_compat=False,
    )

    assert canonical is not None
    assert errors == []
    assert validate_canonical_hypothesis_report(canonical, evidence_dir) == []
    assert not (evidence_dir / "hypothesis_report.json").exists()


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda report: report["hypotheses"].__setitem__(
                0, {**report["hypotheses"][0], "category": "Invalid"}
            ),
            "category is not canonical",
        ),
        (
            lambda report: report["hypotheses"][0].__setitem__(
                "evidence_references", ["stage3_missing.json"]
            ),
            "not in evidence/ directory",
        ),
        (
            lambda report: report.__setitem__("hypotheses", report["hypotheses"][:3]),
            "HYPOTHESIS_COUNT_OUT_OF_RANGE",
        ),
    ],
)
def test_canonicalize_report_sections_rejects_invalid_hypothesis_contract(
    tmp_path: Path,
    mutate,
    expected: str,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    mutate(payload["hypothesis_report"])

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert canonical is None
    assert expected in "\n".join(errors)


def test_canonicalize_report_sections_accepts_bounded_recommendations(
    tmp_path: Path,
) -> None:
    evidence_dir = _write_evidence(tmp_path)

    canonical, errors = canonicalize_report_sections(
        _payload(),
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert errors == []
    assert canonical is not None
    assert canonical["schema_version"] == "hybrid_report_sections/v1"
    assert len(canonical["pipeline_recommendations"]) == 2
    assert REPORT_SECTIONS_FILENAME == "report_sections.json"
    assert not (evidence_dir / "hypothesis_report.json").exists()


@pytest.mark.parametrize(
    "text",
    [
        "Prioritize NINTEDANIB testing before advancing target selection.",
        "Prioritize 7 experiments before advancing target selection.",
        "[source: evidence/assessment_results.json] Prioritize FN1 validation.",
        "FN1 is a supported candidate in deterministic analysis.",
        "Prioritize FN1 validation\nbefore advancing target selection.",
        (
            "Prioritize orthogonal validation of FN1 before advancing target "
            "selection. Evaluate CD4 signals in future mechanistic assays."
        ),
    ],
)
def test_canonicalize_report_sections_rejects_unsafe_recommendation_text(
    tmp_path: Path,
    text: str,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    payload["pipeline_recommendations"][0]["text"] = text

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert canonical is None
    assert errors


@pytest.mark.parametrize("count", [1, 5])
def test_canonicalize_report_sections_rejects_invalid_recommendation_count(
    tmp_path: Path,
    count: int,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    payload["pipeline_recommendations"] = payload["pipeline_recommendations"][:count]
    while len(payload["pipeline_recommendations"]) < count:
        payload["pipeline_recommendations"].append(
            {
                "text": "Prioritize FN1 validation before advancing target selection.",
                "supporting_sources": ["evidence/assessment_results.json"],
            }
        )

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert canonical is None
    assert "pipeline_recommendations" in "\n".join(errors)


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        (
            ["evidence/assessment_results.json", "evidence/assessment_results.json"],
            "must be unique",
        ),
        (["evidence/not_allowed.json"], "deterministic evidence paths"),
        (
            [
                "evidence/assessment_results.json",
                "evidence/stage1_FN1--CD4.json",
                "evidence/stage1_FN1--SDC2.json",
                "evidence/stage3_CD4.json",
            ],
            "report_sections payload is invalid",
        ),
    ],
)
def test_canonicalize_report_sections_rejects_invalid_recommendation_sources(
    tmp_path: Path,
    sources: list[str],
    expected: str,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    payload["pipeline_recommendations"][0]["supporting_sources"] = sources

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert canonical is None
    assert expected in "\n".join(errors)


def test_canonicalize_report_sections_ignores_caller_entity_allowlist(
    tmp_path: Path,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    payload["pipeline_recommendations"][0]["text"] = (
        "Prioritize NINTEDANIB testing before advancing target selection."
    )
    report_data = _report_data()
    report_data["allowed_genes"] = ["CD4", "FN1", "NINTEDANIB"]

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        report_data,
    )

    assert canonical is None
    assert "Unsupported entity token" in "\n".join(errors)
