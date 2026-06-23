from __future__ import annotations

import json
from pathlib import Path


def _minimal_report() -> dict[str, object]:
    return {
        "schema_version": "hypothesis_report.v2",
        "disease": "pulmonary fibrosis",
        "hypotheses_generated": 1,
        "hypotheses_retained": 1,
        "hypotheses": [
            {
                "rank": 1,
                "title": "ICAM1-MUC1 epithelial axis",
                "core_claim": "Open Targets, ChEMBL, Census, and STRING evidence are integrated.",
                "evidence_references": [
                    "ot_ICAM1.json",
                    "chembl_ICAM1.json",
                    "stage1_ICAM1--MUC1.json",
                    "string_ICAM1.json",
                ],
                "validation_approach": "AT2-resolved perturbation assay.",
            }
        ],
    }


def _judge_payload() -> dict[str, object]:
    return {
        "open_targets": {
            "score": 2,
            "evidence_span": "Open Targets supports ICAM1 in pulmonary fibrosis.",
            "reason": "Target-disease association is connected to prioritization.",
        },
        "chembl_druggability": {
            "score": 2,
            "evidence_span": "ChEMBL bioactivity supports druggability.",
            "reason": "Drug-like evidence is connected to intervention logic.",
        },
        "census_cell_type": {
            "score": 2,
            "evidence_span": "Census AT2 co-expression supports cell-type specificity.",
            "reason": "Cell-type evidence is connected to the mechanism.",
        },
        "string_network": {
            "score": 2,
            "evidence_span": "STRING network supports an interaction module.",
            "reason": "Network evidence is connected to the mechanism.",
        },
        "negative_controls": {
            "gwas_intrusion": False,
            "literature_search_intrusion": False,
            "html_report_intrusion": False,
            "evidence_span": "",
            "reason": "No negative-control evidence was used.",
        },
    }


def test_output_grounding_derives_complete_strict_fields() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.evaluate_selective8_output_grounding import (
        derive_output_grounding_fields,
    )

    derived = derive_output_grounding_fields(_judge_payload(), validation_passed=True)

    assert derived["required_modality_count_strict"] == 4
    assert derived["required_modality_count_lenient"] == 4
    assert derived["string_mechanism_present"] is True
    assert derived["negative_control_intrusion"] is False
    assert derived["complete_evidence_grounding_output_strict"] is True
    assert derived["complete_evidence_grounding_validated_strict"] is True


def test_output_grounding_validation_failure_blocks_validated_complete() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.evaluate_selective8_output_grounding import (
        derive_output_grounding_fields,
    )

    derived = derive_output_grounding_fields(_judge_payload(), validation_passed=False)

    assert derived["complete_evidence_grounding_output_strict"] is True
    assert derived["complete_evidence_grounding_validated_strict"] is False


def test_output_grounding_aggregate_counts_missing_and_errors_as_zero() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.evaluate_selective8_output_grounding import (
        aggregate_rows,
    )

    rows = [
        {
            "mode": "middleware_plus_governor",
            "report_present": True,
            "validation_passed": True,
            "judge_error": None,
            "required_modality_count_strict": 4,
            "complete_evidence_grounding_output_strict": True,
            "complete_evidence_grounding_validated_strict": True,
            "string_mechanism_present": True,
            "negative_control_intrusion": False,
        },
        {
            "mode": "middleware_plus_governor",
            "report_present": False,
            "validation_passed": False,
            "judge_error": "missing hypothesis_report.json",
            "required_modality_count_strict": 0,
            "complete_evidence_grounding_output_strict": False,
            "complete_evidence_grounding_validated_strict": False,
            "string_mechanism_present": False,
            "negative_control_intrusion": False,
        },
    ]

    summary = aggregate_rows(rows)
    group = summary["groups"]["middleware_plus_governor"]

    assert group["runs"] == 2
    assert group["report_present_runs"] == 1
    assert group["validation_passed_runs"] == 1
    assert group["judged_runs"] == 1
    assert group["mean_required_modality_count_strict"] == 2.0
    assert group["mean_required_modality_count_strict_validated"] == 2.0
    assert group["complete_evidence_grounding_validated_strict_count"] == 1
    assert group["complete_evidence_grounding_validated_strict_rate"] == 0.5
    assert group["string_mechanism_present_rate"] == 0.5


def test_output_grounding_cli_writes_outputs_without_openai(tmp_path: Path) -> None:
    from docs.benchmarks.hypothesis_generation_consistency.evaluate_selective8_output_grounding import (
        main,
    )

    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "hypothesis_report.json").write_text(
        json.dumps(_minimal_report()),
        encoding="utf-8",
    )
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    (result_dir / "benchmark_results.json").write_text(
        json.dumps(
            {
                "trials": [
                    {
                        "model": "qwen3.5:35b",
                        "mode": "middleware_plus_governor",
                        "repeat": 1,
                        "run_id": "run_01",
                        "workspace": str(workspace),
                        "validation": {
                            "validation_passed": True,
                            "hypothesis_report": str(
                                evidence / "hypothesis_report.json"
                            ),
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert main([str(result_dir), "--skip-openai"]) == 0

    payload = json.loads(
        (result_dir / "output_grounding_gpt4o_mini_scores.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["rows"][0]["judge_error"] == "skipped openai judge"
    assert payload["aggregate"]["groups"]["middleware_plus_governor"]["runs"] == 1
    assert (result_dir / "output_grounding_gpt4o_mini_scores.md").exists()
