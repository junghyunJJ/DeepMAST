from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from argparse import Namespace
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
    HYPOTHESIS_WRITER_RESUME_MESSAGE,
    build_hypothesis_writer_resume_instruction,
    clean_hypothesis_benchmark_workspace,
    check_hypothesis_scope,
    check_hypothesis_scope_untraced,
    find_forbidden_hypothesis_artifacts,
    parse_args,
    prepare_trial_workspace,
    resolve_trial_sources,
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


def test_skill_name_from_read_skill_path_handles_project_relative_path() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.activation_trace import (
        skill_name_from_read_skill_path,
    )

    assert (
        skill_name_from_read_skill_path("skills/string-database/SKILL.md")
        == "string-database"
    )
    assert (
        skill_name_from_read_skill_path(
            "/tmp/worktree/skills/compare-census-gene-pair-by-cell-type/SKILL.md"
        )
        == "compare-census-gene-pair-by-cell-type"
    )
    assert skill_name_from_read_skill_path("evidence/stage3_ICAM1.json") is None


def test_extract_hypothesis_writer_read_skill_calls_ignores_other_nodes() -> None:
    from langchain_core.messages import AIMessage

    from docs.benchmarks.hypothesis_generation_consistency.activation_trace import (
        extract_read_skill_file_calls,
    )

    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_skill_file",
                "args": {"skill_path": "skills/string-database/SKILL.md"},
                "id": "call_1",
            }
        ],
    )

    exposed = ("drug-target-hypothesis", "string-database")
    assert extract_read_skill_file_calls(
        node_path="orchestrator > hypothesis_writer",
        node_name="hypothesis_writer",
        node_data={"messages": [message]},
        exposed_skill_names=exposed,
        scope="hypothesis_writer",
    ) == [
        {
            "skill_name": "string-database",
            "skill_path": "skills/string-database/SKILL.md",
            "tool_call_id": "call_1",
            "node_path": "orchestrator > hypothesis_writer",
            "node_name": "hypothesis_writer",
            "registered": True,
        }
    ]

    assert extract_read_skill_file_calls(
        node_path="orchestrator > finalize_report",
        node_name="finalize_report",
        node_data={"messages": [message]},
        exposed_skill_names=exposed,
        scope="hypothesis_writer",
    ) == []


def test_run_drug_target_traced_parse_args_accepts_activation_flags() -> None:
    from scripts.run_drug_target_traced import parse_args as parse_traced_args

    args = parse_traced_args(
        [
            "--data-dir",
            "/tmp/example",
            "--skip-evidence-assessor",
            "--hypothesis-skill-set",
            "expanded6",
            "--skill-activation-mode",
            "middleware_only",
            "--activation-trace-json",
            "/tmp/example/activation_trace.json",
        ]
    )

    assert args.hypothesis_skill_set == "expanded6"
    assert args.skill_activation_mode == "middleware_only"
    assert args.activation_trace_json == "/tmp/example/activation_trace.json"


def test_activation_matrix_default_plan_has_12_trials() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
        build_trial_plan,
    )

    trials = build_trial_plan(
        models=("qwen3.5:35b", "qwen3.5:122b"),
        ports=(5000, 6000, 7000),
        modes=("middleware_only", "middleware_plus_activator"),
    )

    assert len(trials) == 12
    assert trials[0] == {
        "model": "qwen3.5:35b",
        "port": 5000,
        "mode": "middleware_only",
        "run_id": "qwen35b_middleware_only_port5000",
    }
    assert trials[-1] == {
        "model": "qwen3.5:122b",
        "port": 7000,
        "mode": "middleware_plus_activator",
        "run_id": "qwen122b_middleware_plus_activator_port7000",
    }


def test_activation_matrix_unload_request_payload() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
        build_ollama_unload_payload,
    )

    assert build_ollama_unload_payload("qwen3.5:122b") == {
        "model": "qwen3.5:122b",
        "keep_alive": 0,
    }


def test_activation_matrix_marks_missing_trace_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from docs.benchmarks.hypothesis_generation_consistency import run_activation_matrix

    def fake_copy_source_workspace(
        source: Path,
        destination: Path,
        *,
        force: bool,
    ) -> None:
        destination.mkdir(parents=True)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

    monkeypatch.setattr(
        run_activation_matrix,
        "copy_source_workspace",
        fake_copy_source_workspace,
    )
    monkeypatch.setattr(run_activation_matrix.subprocess, "run", fake_run)
    monkeypatch.setattr(
        run_activation_matrix,
        "validate_trial_output",
        lambda run_id, workspace, *, elapsed_s, error: {
            "run_id": run_id,
            "validation_passed": True,
            "error": error,
        },
    )

    row = run_activation_matrix.run_one_trial(
        trial={
            "model": "qwen3.5:35b",
            "port": 5000,
            "mode": "middleware_only",
            "run_id": "run_missing_trace",
        },
        source=tmp_path / "source",
        workspace_root=tmp_path / "workspaces",
        output_root=tmp_path,
        disease="pulmonary fibrosis",
        timeout_minutes=1,
        force=True,
    )

    assert row["activation_trace_valid"] is False
    assert "activation trace missing" in row["activation_trace_error"]
    assert row["activated_skill_names"] == []
    assert row["activated_added_skill_names"] == []


def test_activation_matrix_marks_malformed_trace_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from docs.benchmarks.hypothesis_generation_consistency import run_activation_matrix

    def fake_copy_source_workspace(
        source: Path,
        destination: Path,
        *,
        force: bool,
    ) -> None:
        destination.mkdir(parents=True)

    def fake_run(command, *args, **kwargs):
        trace_path = Path(command[command.index("--activation-trace-json") + 1])
        trace_path.write_text("{not json", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(
        run_activation_matrix,
        "copy_source_workspace",
        fake_copy_source_workspace,
    )
    monkeypatch.setattr(run_activation_matrix.subprocess, "run", fake_run)
    monkeypatch.setattr(
        run_activation_matrix,
        "validate_trial_output",
        lambda run_id, workspace, *, elapsed_s, error: {
            "run_id": run_id,
            "validation_passed": True,
            "error": error,
        },
    )

    row = run_activation_matrix.run_one_trial(
        trial={
            "model": "qwen3.5:35b",
            "port": 5000,
            "mode": "middleware_only",
            "run_id": "run_malformed_trace",
        },
        source=tmp_path / "source",
        workspace_root=tmp_path / "workspaces",
        output_root=tmp_path,
        disease="pulmonary fibrosis",
        timeout_minutes=1,
        force=True,
    )

    assert row["activation_trace_valid"] is False
    assert "JSONDecodeError" in row["activation_trace_error"]
    assert row["activated_skill_names"] == []


def test_activation_matrix_aggregate_excludes_invalid_trace_denominator() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
        aggregate_activation,
    )

    aggregate = aggregate_activation(
        [
            {
                "model": "qwen3.5:35b",
                "mode": "middleware_only",
                "returncode": 0,
                "validation": {"validation_passed": True},
                "activation_trace_valid": True,
                "activated_skill_names": ["string-database"],
                "activated_added_skill_names": ["string-database"],
            },
            {
                "model": "qwen3.5:35b",
                "mode": "middleware_only",
                "returncode": 0,
                "validation": {"validation_passed": True},
                "activation_trace_valid": False,
                "activated_skill_names": [],
                "activated_added_skill_names": [],
            },
        ]
    )

    group = aggregate["groups"]["qwen3.5:35b::middleware_only"]
    assert group["runs"] == 2
    assert group["successes"] == 2
    assert group["validation_passes"] == 2
    assert group["activation_trace_valid_runs"] == 1
    assert group["activation_trace_invalid_runs"] == 1
    assert group["mean_activation_count"] == 1.0
    assert group["skill_activation_rates"] == {"string-database": 1.0}
    assert group["added_skill_activation_rates"] == {"string-database": 1.0}


def test_activation_matrix_unloads_active_model_when_trial_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from docs.benchmarks.hypothesis_generation_consistency import run_activation_matrix

    source = tmp_path / "source"
    source.mkdir()
    unload_calls: list[tuple[str, tuple[int, ...]]] = []

    monkeypatch.setattr(
        run_activation_matrix,
        "parse_args",
        lambda: Namespace(
            source=str(source),
            output_root=str(tmp_path / "out"),
            workspace_root=str(tmp_path / "workspaces"),
            disease="pulmonary fibrosis",
            timeout_minutes=1,
            force=True,
        ),
    )
    monkeypatch.setattr(
        run_activation_matrix,
        "build_trial_plan",
        lambda *, models, ports, modes: [
            {
                "model": "qwen3.5:35b",
                "port": 5000,
                "mode": "middleware_only",
                "run_id": "run_raises",
            }
        ],
    )

    def fake_run_one_trial(**kwargs):
        raise RuntimeError("trial failed")

    def fake_unload_model_from_ports(model: str, ports) -> list[dict]:
        unload_calls.append((model, tuple(ports)))
        return [{"model": model, "ports": list(ports), "ok": True}]

    monkeypatch.setattr(run_activation_matrix, "run_one_trial", fake_run_one_trial)
    monkeypatch.setattr(
        run_activation_matrix,
        "unload_model_from_ports",
        fake_unload_model_from_ports,
    )

    with pytest.raises(RuntimeError, match="trial failed"):
        run_activation_matrix.main()

    assert unload_calls == [("qwen3.5:35b", (5000, 6000, 7000))]
    payload = json.loads((tmp_path / "out" / "benchmark_results.json").read_text())
    assert payload["runner_error"] == "RuntimeError: trial failed"
    assert payload["unload_events"] == [
        {"model": "qwen3.5:35b", "ports": [5000, 6000, 7000], "ok": True}
    ]


def test_activation_matrix_direct_script_help_works() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "docs/benchmarks/hypothesis_generation_consistency/run_activation_matrix.py",
            "--help",
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0
    assert "Run expanded6 activation comparison" in completed.stdout


def test_activation_matrix_default_workspace_root_is_sibling_to_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from docs.benchmarks.hypothesis_generation_consistency import run_activation_matrix

    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(run_activation_matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(run_activation_matrix.time, "strftime", lambda _: "expanded6_activation_fixed")
    monkeypatch.setattr(
        run_activation_matrix,
        "parse_args",
        lambda: Namespace(
            source=str(source),
            output_root="",
            workspace_root="",
            disease="pulmonary fibrosis",
            timeout_minutes=1,
            force=True,
        ),
    )
    monkeypatch.setattr(
        run_activation_matrix,
        "build_trial_plan",
        lambda *, models, ports, modes: [],
    )

    assert run_activation_matrix.main() == 0

    assert (
        tmp_path
        / "docs/benchmarks/hypothesis_generation_consistency/results/expanded6_activation_fixed"
    ).is_dir()
    assert (
        tmp_path
        / "docs/benchmarks/hypothesis_generation_consistency/workspaces/expanded6_activation_fixed"
    ).is_dir()
    assert not (
        tmp_path
        / "docs/benchmarks/hypothesis_generation_consistency/results/workspaces/expanded6_activation_fixed"
    ).exists()


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
    (source / "drug_report_render.json").write_text("{}", encoding="utf-8")
    (source / "drug_report_reference_card.json").write_text("{}", encoding="utf-8")
    (source / "part4_candidate_selection.json").write_text("{}", encoding="utf-8")
    (source / "part4_therapeutic_synthesis.md").write_text("stale", encoding="utf-8")
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
    (evidence / "hypothesis_report_last_rejection.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (evidence / "hypothesis_draft.json").write_text("{}", encoding="utf-8")

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
    assert not (workspace / "drug_report_render.json").exists()
    assert not (workspace / "drug_report_reference_card.json").exists()
    assert not (workspace / "part4_candidate_selection.json").exists()
    assert not (workspace / "part4_therapeutic_synthesis.md").exists()
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
    assert not (workspace / "evidence" / "hypothesis_draft.json").exists()
    assert not (workspace / "evidence" / "hypothesis_report.json").exists()
    assert not (
        workspace / "evidence" / "hypothesis_report_last_rejection.json"
    ).exists()


def test_hypothesis_writer_resume_message_preserves_output_guards() -> None:
    assert "save_hypothesis_report" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "write_todos" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "write_file" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "/tmp" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "evidence/hypothesis_report.json" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "target-cell-depleted" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "gene-level/actionability-only" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "ot_<GENE>.json" in HYPOTHESIS_WRITER_RESUME_MESSAGE


def test_build_hypothesis_writer_resume_instruction_includes_exact_data_dir(
    tmp_path: Path,
) -> None:
    instruction = build_hypothesis_writer_resume_instruction(tmp_path)

    assert str(tmp_path) in instruction
    assert "target-cell-depleted" in instruction
    assert "save_hypothesis_report" in instruction


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
    (workspace / "evidence" / "hypothesis_report_last_rejection.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (workspace / "evidence" / "hypothesis_draft.json").write_text(
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
        "evidence/hypothesis_draft.json",
        "evidence/hypothesis_report.json",
        "evidence/hypothesis_report_last_rejection.json",
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
    assert not (workspace / "evidence" / "hypothesis_draft.json").exists()
    assert not (workspace / "evidence" / "hypothesis_report.json").exists()
    assert not (
        workspace / "evidence" / "hypothesis_report_last_rejection.json"
    ).exists()


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


def test_resolve_trial_sources_repeats_single_source(tmp_path: Path) -> None:
    source = tmp_path / "source"

    sources = resolve_trial_sources(str(source), None, 3)

    assert sources == [source, source, source]


def test_resolve_trial_sources_requires_sources_count_to_match_runs(
    tmp_path: Path,
) -> None:
    first = tmp_path / "source1"
    second = tmp_path / "source2"

    with pytest.raises(ValueError, match="--sources count"):
        resolve_trial_sources(str(first), [str(first), str(second)], 3)


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
