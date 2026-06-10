from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from docs.benchmarks.hypothesis_generation_consistency.analysis import (
    aggregate_trial_rows,
    jaccard,
    summarize_report,
)
from docs.benchmarks.hypothesis_generation_consistency.compare_skill_sets import (
    compare_pair,
    evidence_fingerprint,
    main as compare_skill_sets_main,
    render_markdown,
)
from docs.benchmarks.hypothesis_generation_consistency.run_benchmark import (
    CURRENT4_HYPOTHESIS_WRITER_SKILLS,
    EXPANDED6_HYPOTHESIS_WRITER_SKILLS,
    clean_hypothesis_benchmark_workspace,
    check_hypothesis_scope,
    check_hypothesis_scope_untraced,
    find_forbidden_hypothesis_artifacts,
    parse_args,
    prepare_trial_workspace,
    resolve_hypothesis_writer_skill_names,
    validate_trial_output,
)


def test_hypothesis_generation_consistency_package_imports() -> None:
    module = importlib.import_module(
        "docs.benchmarks.hypothesis_generation_consistency"
    )
    assert module.__name__ == "docs.benchmarks.hypothesis_generation_consistency"


def test_current4_and_expanded6_skill_sets_are_explicit() -> None:
    assert CURRENT4_HYPOTHESIS_WRITER_SKILLS == (
        "drug-target-hypothesis",
        "opentargets-database",
        "gwas-database",
        "chembl-database",
    )
    assert EXPANDED6_HYPOTHESIS_WRITER_SKILLS == (
        "drug-target-hypothesis",
        "opentargets-database",
        "gwas-database",
        "chembl-database",
        "compare-census-gene-pair-by-cell-type",
        "string-database",
    )


def test_resolve_hypothesis_writer_skill_names_returns_tuple_copy() -> None:
    first = resolve_hypothesis_writer_skill_names("expanded6")
    second = resolve_hypothesis_writer_skill_names("expanded6")

    assert first == EXPANDED6_HYPOTHESIS_WRITER_SKILLS
    assert first is not second


def test_resolve_hypothesis_writer_skill_names_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown skill set"):
        resolve_hypothesis_writer_skill_names("expanded")


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


def _write_workspace_report(
    workspace: Path,
    report: dict,
    *,
    assessment_payload: dict | None = None,
) -> None:
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "assessment_results.json").write_text(
        json.dumps(assessment_payload or {"stage3_candidates": [{"gene": "ICAM1"}]}),
        encoding="utf-8",
    )
    (evidence / "stage1_filter_results.json").write_text(
        json.dumps({"results": []}),
        encoding="utf-8",
    )
    (evidence / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )


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


def test_aggregate_trial_rows_pairwise_metrics_use_validation_passed_runs() -> None:
    invalid_report = _report_two()
    invalid_report["hypotheses"][0]["title"] = "invalid divergent title"
    rows = [
        {
            "run_id": "run_valid",
            "success": True,
            "validation_passed": True,
            "report_summary": summarize_report(_report_one()),
        },
        {
            "run_id": "run_invalid",
            "success": True,
            "validation_passed": False,
            "report_summary": summarize_report(invalid_report),
        },
    ]

    aggregate = aggregate_trial_rows(rows)

    assert aggregate["successful_runs"] == 2
    assert aggregate["validation_passed_runs"] == 1
    assert aggregate["hypothesis_count_values"] == [2]
    assert aggregate["mean_pairwise_title_similarity"] is None
    assert aggregate["mean_pairwise_core_claim_similarity"] is None


def test_evidence_fingerprint_ignores_generated_hypothesis_report(
    tmp_path: Path,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    _write_workspace_report(left, _report_one())
    _write_workspace_report(right, _report_two())

    assert evidence_fingerprint(left) == evidence_fingerprint(right)


def test_evidence_fingerprint_detects_non_generated_evidence_mismatch(
    tmp_path: Path,
) -> None:
    current4 = tmp_path / "current4"
    expanded6 = tmp_path / "expanded6"
    _write_workspace_report(current4, _report_one())
    _write_workspace_report(
        expanded6,
        _report_one(),
        assessment_payload={"stage3_candidates": [{"gene": "MUC1"}]},
    )

    assert evidence_fingerprint(current4)["sha256"] != evidence_fingerprint(
        expanded6
    )["sha256"]

    row = compare_pair(
        {
            "case_id": "ipf_35b_run1",
            "current4": str(current4),
            "expanded6": str(expanded6),
        }
    )
    assert row["evidence_fingerprint_match"] is False


def test_compare_pair_reports_summary_deltas(tmp_path: Path) -> None:
    current4 = tmp_path / "current4"
    expanded6 = tmp_path / "expanded6"
    _write_workspace_report(current4, _report_one())
    _write_workspace_report(expanded6, _report_two())

    row = compare_pair(
        {
            "case_id": "ipf_35b_run1",
            "current4": str(current4),
            "expanded6": str(expanded6),
        }
    )

    assert row["case_id"] == "ipf_35b_run1"
    assert row["current4_hypothesis_count"] == 2
    assert row["expanded6_hypothesis_count"] == 2
    assert row["gene_jaccard"] == 1.0
    assert row["evidence_ref_jaccard"] == 1.0
    assert 0.0 < row["title_similarity"] <= 1.0
    assert row["evidence_fingerprint_match"] is True


def test_render_markdown_includes_pairwise_metrics() -> None:
    markdown = render_markdown(
        [
            {
                "case_id": "ipf_35b_run1",
                "current4_hypothesis_count": 5,
                "expanded6_hypothesis_count": 6,
                "current4_topn_missing": [],
                "expanded6_topn_missing": [],
                "gene_jaccard": 0.83,
                "evidence_ref_jaccard": 0.77,
                "title_similarity": 0.62,
                "core_claim_similarity": 0.58,
                "evidence_fingerprint_match": True,
            }
        ]
    )

    assert "# Current4 vs Expanded6 Hypothesis Comparison" in markdown
    assert "| ipf_35b_run1 | 5 | 6 | - | - | 0.83 | 0.77 | 0.62 | 0.58 | True |" in markdown


def test_compare_skill_sets_main_rejects_non_object_pairs_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pairs_json = tmp_path / "pairs.json"
    pairs_json.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare_skill_sets.py",
            "--pairs-json",
            str(pairs_json),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    with pytest.raises(
        SystemExit,
        match="--pairs-json must contain a JSON object with a non-empty 'pairs' list",
    ):
        compare_skill_sets_main()


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


def test_prepare_trial_workspace_removes_prior_report_artifacts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    evidence = source / "evidence"
    history = source / "conversation_history"
    large_tool_results = source / "large_tool_results"
    evidence.mkdir(parents=True)
    history.mkdir()
    large_tool_results.mkdir()
    (source / "lr_candidates.json").write_text("{}", encoding="utf-8")
    (source / "drug.md").write_text("stale drug report", encoding="utf-8")
    (source / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    (source / "drug_report_reference_card.json").write_text("{}", encoding="utf-8")
    (source / "report_expansions.json").write_text("{}", encoding="utf-8")
    (source / "target_assessment.json").write_text("{}", encoding="utf-8")
    (source / "hypothesis_report.json").write_text("{}", encoding="utf-8")
    (source / "hypothesis_report.tmp.json").write_text("{}", encoding="utf-8")
    (source / "Hypothesis_Report_Mixed.JSON").write_text("{}", encoding="utf-8")
    (source / "hypothesis_report_draft.json").write_text("{}", encoding="utf-8")
    (source / "report_data.json").write_text("{}", encoding="utf-8")
    (source / "report_validation.json").write_text("{}", encoding="utf-8")
    (source / "trace_20260528_113442.log").write_text("stale", encoding="utf-8")
    (source / "token_usage_20260528_113442.json").write_text("{}", encoding="utf-8")
    (history / "prior.md").write_text("old conversation", encoding="utf-8")
    (large_tool_results / "prior-tool-call").write_text(
        '{"data_dir": "res_ipf_ollama"}',
        encoding="utf-8",
    )
    (evidence / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "ICAM1"}]}),
        encoding="utf-8",
    )
    (evidence / "hypothesis_report.json").write_text(
        json.dumps({"schema_version": "hypothesis_report.v2"}),
        encoding="utf-8",
    )

    workspace = prepare_trial_workspace(
        source,
        tmp_path / "workspaces",
        "run_01",
        force=True,
    )

    assert (workspace / "lr_candidates.json").exists()
    assert (workspace / "evidence" / "assessment_results.json").exists()
    assert not (workspace / "drug.md").exists()
    assert not (workspace / "drug_report.html").exists()
    assert not (workspace / "drug_report_reference_card.json").exists()
    assert not (workspace / "report_expansions.json").exists()
    assert not (workspace / "target_assessment.json").exists()
    assert not (workspace / "hypothesis_report.json").exists()
    assert not (workspace / "hypothesis_report.tmp.json").exists()
    assert not (workspace / "Hypothesis_Report_Mixed.JSON").exists()
    assert not (workspace / "hypothesis_report_draft.json").exists()
    assert not (workspace / "report_data.json").exists()
    assert not (workspace / "report_validation.json").exists()
    assert not (workspace / "trace_20260528_113442.log").exists()
    assert not (workspace / "token_usage_20260528_113442.json").exists()
    assert not (workspace / "conversation_history").exists()
    assert not (workspace / "large_tool_results").exists()
    assert not (workspace / "evidence" / "hypothesis_report.json").exists()


def test_clean_hypothesis_benchmark_workspace_reports_removed_artifacts(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "evidence").mkdir(parents=True)
    (workspace / "conversation_history").mkdir()
    (workspace / "large_tool_results").mkdir()
    (workspace / "drug.md").write_text("stale", encoding="utf-8")
    (workspace / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    (workspace / "drug_report_reference_card.json").write_text("{}", encoding="utf-8")
    (workspace / "report_expansions.json").write_text("{}", encoding="utf-8")
    (workspace / "target_assessment.json").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report.json").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report.tmp.json").write_text("{}", encoding="utf-8")
    (workspace / "Hypothesis_Report_Mixed.JSON").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report_draft.json").write_text("{}", encoding="utf-8")
    (workspace / "report_data.json").write_text("{}", encoding="utf-8")
    (workspace / "report_validation.json").write_text("{}", encoding="utf-8")
    (workspace / "token_usage_20260528_113442.json").write_text("{}", encoding="utf-8")
    (workspace / "trace_20260528_113442.log").write_text("stale", encoding="utf-8")
    (workspace / "conversation_history" / "prior.md").write_text(
        "old conversation",
        encoding="utf-8",
    )
    (workspace / "large_tool_results" / "old-tool-result").write_text(
        "stale payload",
        encoding="utf-8",
    )
    (workspace / "evidence" / "hypothesis_report.json").write_text(
        "{}",
        encoding="utf-8",
    )

    removed = clean_hypothesis_benchmark_workspace(workspace)

    assert removed == [
        "drug.md",
        "drug_report.html",
        "drug_report_reference_card.json",
        "report_expansions.json",
        "target_assessment.json",
        "report_data.json",
        "report_validation.json",
        "evidence/hypothesis_report.json",
        "conversation_history/",
        "large_tool_results/",
        "hypothesis_report.json",
        "hypothesis_report.tmp.json",
        "hypothesis_report_draft.json",
        "Hypothesis_Report_Mixed.JSON",
        "token_usage_20260528_113442.json",
        "trace_20260528_113442.log",
    ]
    assert not (workspace / "drug.md").exists()
    assert not (workspace / "drug_report.html").exists()
    assert not (workspace / "drug_report_reference_card.json").exists()
    assert not (workspace / "report_expansions.json").exists()
    assert not (workspace / "target_assessment.json").exists()
    assert not (workspace / "hypothesis_report.json").exists()
    assert not (workspace / "hypothesis_report.tmp.json").exists()
    assert not (workspace / "Hypothesis_Report_Mixed.JSON").exists()
    assert not (workspace / "hypothesis_report_draft.json").exists()
    assert not (workspace / "report_data.json").exists()
    assert not (workspace / "report_validation.json").exists()
    assert not (workspace / "conversation_history").exists()
    assert not (workspace / "large_tool_results").exists()
    assert not (workspace / "token_usage_20260528_113442.json").exists()
    assert not (workspace / "trace_20260528_113442.log").exists()
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


def test_check_hypothesis_scope_untraced_restores_tracing_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    (source / "evidence").mkdir(parents=True)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "test-langchain-key")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-langsmith-key")

    result = check_hypothesis_scope_untraced(source)

    assert result["scope"] == "hypothesis"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGCHAIN_API_KEY"] == "test-langchain-key"
    assert os.environ["LANGSMITH_API_KEY"] == "test-langsmith-key"


def test_dry_run_cli_suppresses_langsmith_tracing() -> None:
    source = Path("res_ipf_ollama_tmp")
    if not source.exists():
        pytest.skip("benchmark source workspace is not available")
    env = {
        **os.environ,
        "LANGCHAIN_TRACING_V2": "true",
        "LANGSMITH_TRACING": "true",
        "LANGCHAIN_API_KEY": "test-langchain-key",
        "LANGSMITH_API_KEY": "test-langsmith-key",
    }

    completed = subprocess.run(
        [
            sys.executable,
            "docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py",
            "--source",
            str(source),
            "--runs",
            "10",
            "--dry-run",
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        env=env,
    )

    assert completed.returncode == 0
    assert "LangSmith" not in completed.stderr
    assert "RateLimit" not in completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["file_count"] == 64
    assert payload["contrast_count"] == 10
    assert payload["errors"] == []


def test_parse_args_uses_ollama_when_provider_env_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setattr(sys, "argv", ["run_benchmark.py"])

    args = parse_args()

    assert args.provider == "ollama"


def test_parse_args_accepts_expanded6_skill_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_benchmark.py", "--skill-set", "expanded6"],
    )

    args = parse_args()

    assert args.skill_set == "expanded6"


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


def test_validate_trial_output_rejects_non_object_report(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "hypothesis_report.json").write_text("[]", encoding="utf-8")

    row = validate_trial_output("run_01", workspace, elapsed_s=1.25, error=None)

    assert row["success"] is False
    assert row["validation_passed"] is False
    assert row["report_summary"] is None
    assert "JSON object" in row["error"]
    assert "list" in row["error"]


def test_validate_trial_output_marks_forbidden_draft_artifact_invalid(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (workspace / "hypothesis_report.json").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report.tmp.json").write_text("{}", encoding="utf-8")
    (workspace / "Hypothesis_Report_Mixed.JSON").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report_draft.json").write_text("{}", encoding="utf-8")
    (evidence / "hypothesis_report.json").write_text(
        json.dumps(_report_one()),
        encoding="utf-8",
    )

    row = validate_trial_output("run_01", workspace, elapsed_s=1.25, error=None)

    assert row["success"] is True
    assert row["validation_passed"] is False
    assert row["forbidden_artifacts"] == [
        "hypothesis_report.json",
        "hypothesis_report.tmp.json",
        "hypothesis_report_draft.json",
        "Hypothesis_Report_Mixed.JSON",
    ]


def test_find_forbidden_hypothesis_artifacts_reports_root_level_variants(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (workspace / "hypothesis_report.json").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report_a.json").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report_b.json").write_text("{}", encoding="utf-8")
    (workspace / "Hypothesis_Report_Mixed.JSON").write_text("{}", encoding="utf-8")
    (evidence / "hypothesis_report.json").write_text("{}", encoding="utf-8")

    artifacts = find_forbidden_hypothesis_artifacts(workspace)

    assert artifacts == [
        "hypothesis_report.json",
        "hypothesis_report_a.json",
        "hypothesis_report_b.json",
        "Hypothesis_Report_Mixed.JSON",
    ]


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
