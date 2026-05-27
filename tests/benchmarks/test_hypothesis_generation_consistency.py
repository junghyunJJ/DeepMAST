from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from docs.benchmarks.hypothesis_generation_consistency.analysis import (
    aggregate_trial_rows,
    jaccard,
    summarize_report,
)
from docs.benchmarks.hypothesis_generation_consistency.run_benchmark import (
    check_hypothesis_scope,
    prepare_trial_workspace,
    validate_trial_output,
)


def test_hypothesis_generation_consistency_package_imports() -> None:
    module = importlib.import_module(
        "docs.benchmarks.hypothesis_generation_consistency"
    )
    assert module.__name__ == "docs.benchmarks.hypothesis_generation_consistency"


def _report_one() -> dict:
    return {
        "schema_version": "hypothesis_report.v2",
        "hypotheses": [
            {
                "title": "ICAM1 ITGB2 adhesion",
                "category": "Mechanism of Action",
                "core_claim": "ICAM1 and ITGB2 drive adhesion.",
                "evidence_references": ["stage1_ICAM1--ITGB2.json", "stage3_ICAM1.json"],
                "biological_entities": {"genes": ["ICAM1", "ITGB2"]},
            },
            {
                "title": "CD47 checkpoint",
                "category": "Therapeutic Strategy",
                "core_claim": "CD47 blockade changes clearance.",
                "evidence_references": ["stage1_THBS1--CD47.json", "stage3_CD47.json"],
                "biological_entities": {"genes": ["THBS1", "CD47"]},
            },
        ],
        "topn_coverage": {"covered": ["CD47", "ICAM1", "ITGB2"], "missing": []},
        "evidence_coverage_pct": 87.5,
        "prediction_grounding_summary": {"unverified": 0, "qualitative": 2},
    }


def _report_two() -> dict:
    report = _report_one()
    report["hypotheses"][0]["title"] = "ICAM1-ITGB2 adhesion signaling"
    report["hypotheses"][0]["core_claim"] = "ICAM1 with ITGB2 supports adhesion."
    return report


def test_jaccard_handles_empty_and_nonempty_sets() -> None:
    assert jaccard(set(), set()) == 1.0
    assert jaccard({"A"}, set()) == 0.0
    assert jaccard({"A", "B"}, {"B", "C"}) == 1 / 3


def test_summarize_report_extracts_structure() -> None:
    summary = summarize_report(_report_one())
    assert summary["schema_version"] == "hypothesis_report.v2"
    assert summary["hypothesis_count"] == 2
    assert summary["category_counts"] == {
        "Mechanism of Action": 1,
        "Therapeutic Strategy": 1,
    }
    assert summary["covered_genes"] == ["CD47", "ICAM1", "ITGB2", "THBS1"]
    assert summary["evidence_refs"] == [
        "stage1_ICAM1--ITGB2.json",
        "stage1_THBS1--CD47.json",
        "stage3_CD47.json",
        "stage3_ICAM1.json",
    ]
    assert summary["topn_missing"] == []
    assert summary["unverified_numeric_predictions"] == 0


def test_aggregate_trial_rows_reports_pairwise_consistency() -> None:
    rows = [
        {
            "run_id": "run_01",
            "success": True,
            "validation_passed": True,
            "report_summary": summarize_report(_report_one()),
        },
        {
            "run_id": "run_02",
            "success": True,
            "validation_passed": True,
            "report_summary": summarize_report(_report_two()),
        },
    ]
    aggregate = aggregate_trial_rows(rows)
    assert aggregate["total_runs"] == 2
    assert aggregate["success_rate"] == 1.0
    assert aggregate["validation_pass_rate"] == 1.0
    assert aggregate["hypothesis_count_values"] == [2]
    assert aggregate["mean_pairwise_gene_jaccard"] == 1.0
    assert 0.0 < aggregate["mean_pairwise_title_similarity"] <= 1.0


def test_aggregate_trial_rows_handles_failed_row_without_summary() -> None:
    rows = [
        {
            "run_id": "run_01",
            "success": True,
            "validation_passed": True,
            "report_summary": summarize_report(_report_one()),
        },
        {
            "run_id": "run_failed",
            "success": False,
            "validation_passed": False,
            "report_summary": None,
        },
    ]

    aggregate = aggregate_trial_rows(rows)

    assert aggregate["total_runs"] == 2
    assert aggregate["successful_runs"] == 1
    assert aggregate["validation_passed_runs"] == 1
    assert aggregate["success_rate"] == 0.5
    assert aggregate["validation_pass_rate"] == 0.5
    assert aggregate["topn_missing_by_run"]["run_failed"] == []
    assert aggregate["unverified_numeric_predictions_by_run"]["run_failed"] is None


def test_prepare_trial_workspace_copies_source_and_removes_stale_report(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    evidence = source / "evidence"
    evidence.mkdir(parents=True)
    (source / "lr_candidates.json").write_text("{}", encoding="utf-8")
    (evidence / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "ICAM1"}]}),
        encoding="utf-8",
    )
    (evidence / "hypothesis_report.json").write_text(
        '{"stale": true}',
        encoding="utf-8",
    )

    workspace = prepare_trial_workspace(
        source,
        tmp_path / "workspaces",
        "run_01",
        force=True,
    )

    assert (workspace / "evidence" / "assessment_results.json").exists()
    assert not (workspace / "evidence" / "hypothesis_report.json").exists()


@pytest.mark.parametrize("run_id", ["absolute", "../escaped"])
def test_prepare_trial_workspace_rejects_escaping_run_id_without_touching_target(
    tmp_path: Path,
    run_id: str,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    workspace_root = tmp_path / "workspaces"
    if run_id == "absolute":
        target = tmp_path / "absolute_escape"
        rejected_run_id = str(target)
    else:
        target = workspace_root / run_id
        rejected_run_id = run_id
    target.mkdir(parents=True)
    sentinel = target / "sentinel.txt"
    sentinel.write_text("preserved", encoding="utf-8")

    with pytest.raises(ValueError):
        prepare_trial_workspace(source, workspace_root, rejected_run_id, force=True)

    assert sentinel.read_text(encoding="utf-8") == "preserved"


def test_check_hypothesis_scope_reports_loader_errors(tmp_path: Path) -> None:
    source = tmp_path / "source"
    evidence = source / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "ICAM1"}]}),
        encoding="utf-8",
    )
    (evidence / "stage1_ICAM1--ITGB2.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )
    result = check_hypothesis_scope(source)
    assert result["scope"] == "hypothesis"
    assert result["file_count"] == 0
    assert result["errors"]


def test_validate_trial_output_marks_missing_report_as_failure(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "evidence").mkdir(parents=True)
    row = validate_trial_output("run_01", workspace, elapsed_s=1.25, error=None)
    assert row["run_id"] == "run_01"
    assert row["success"] is False
    assert row["validation_passed"] is False
    assert "hypothesis_report.json missing" in row["error"]


@pytest.mark.parametrize(
    "report",
    [
        {},
        {
            "schema_version": "hypothesis_report.v2",
            "hypotheses": [],
            "topn_coverage": {"covered": [], "missing": []},
            "prediction_grounding_summary": {"unverified": 0},
        },
    ],
)
def test_validate_trial_output_rejects_structurally_empty_reports(
    tmp_path: Path,
    report: dict,
) -> None:
    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    row = validate_trial_output("run_01", workspace, elapsed_s=1.25, error=None)

    assert row["success"] is True
    assert row["validation_passed"] is False


def test_validate_trial_output_includes_summary_when_invocation_errors_after_report(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "hypothesis_report.json").write_text(
        json.dumps(_report_one()),
        encoding="utf-8",
    )

    row = validate_trial_output(
        "run_01",
        workspace,
        elapsed_s=1.25,
        error="RuntimeError: failed after writing report",
    )

    assert row["success"] is False
    assert row["validation_passed"] is False
    assert row["report_summary"]["hypothesis_count"] == 2
