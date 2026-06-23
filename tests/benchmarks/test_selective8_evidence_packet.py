from __future__ import annotations

import json
from pathlib import Path


def _trial(
    *,
    mode: str = "middleware_plus_governor",
    run_id: str = "run_01",
    activated: list[str] | None = None,
    validation_passed: bool = True,
    trace_valid: bool = True,
    report_path: str | None = None,
) -> dict[str, object]:
    return {
        "model": "qwen3.5:35b",
        "mode": mode,
        "port": 7000,
        "repeat": 1,
        "run_id": run_id,
        "activation_trace_valid": trace_valid,
        "activated_skill_names": activated
        if activated is not None
        else [
            "drug-target-hypothesis",
            "opentargets-database",
            "chembl-database",
            "compare-census-gene-pair-by-cell-type",
            "string-database",
        ],
        "validation": {
            "validation_passed": validation_passed,
            "hypothesis_report": report_path or "/tmp/hypothesis_report.json",
        },
    }


def test_evidence_packet_scores_validated_complete_packet() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.evaluate_selective8_evidence_packet import (
        score_trial,
    )

    scored = score_trial(_trial())

    assert scored["required_skill_hit_count"] == 4
    assert scored["missing_required_skills"] == []
    assert scored["negative_control_skills"] == []
    assert scored["complete_evidence_packet_activation_only"] is True
    assert scored["complete_evidence_packet_validated"] is True


def test_evidence_packet_missing_string_blocks_complete_packet() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.evaluate_selective8_evidence_packet import (
        score_trial,
    )

    scored = score_trial(
        _trial(
            activated=[
                "drug-target-hypothesis",
                "opentargets-database",
                "chembl-database",
                "compare-census-gene-pair-by-cell-type",
            ]
        )
    )

    assert scored["required_skill_hit_count"] == 3
    assert scored["missing_required_skills"] == ["string-database"]
    assert scored["complete_evidence_packet_activation_only"] is False
    assert scored["complete_evidence_packet_validated"] is False


def test_evidence_packet_negative_control_blocks_complete_packet() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.evaluate_selective8_evidence_packet import (
        score_trial,
    )

    scored = score_trial(
        _trial(
            activated=[
                "drug-target-hypothesis",
                "opentargets-database",
                "chembl-database",
                "compare-census-gene-pair-by-cell-type",
                "string-database",
                "gwas-database",
            ]
        )
    )

    assert scored["required_skill_hit_count"] == 4
    assert scored["negative_control_skills"] == ["gwas-database"]
    assert scored["complete_evidence_packet_activation_only"] is False
    assert scored["complete_evidence_packet_validated"] is False


def test_evidence_packet_validation_failure_keeps_activation_only_complete() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.evaluate_selective8_evidence_packet import (
        score_trial,
    )

    scored = score_trial(_trial(validation_passed=False))

    assert scored["complete_evidence_packet_activation_only"] is True
    assert scored["complete_evidence_packet_validated"] is False


def test_evidence_packet_invalid_trace_gets_zero_credit() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.evaluate_selective8_evidence_packet import (
        score_trial,
    )

    scored = score_trial(_trial(trace_valid=False))

    assert scored["required_skill_hit_count"] == 0
    assert scored["missing_required_skills"] == [
        "chembl-database",
        "compare-census-gene-pair-by-cell-type",
        "opentargets-database",
        "string-database",
    ]
    assert scored["complete_evidence_packet_activation_only"] is False
    assert scored["complete_evidence_packet_validated"] is False


def test_evidence_packet_aggregate_counts_validation_gated_denominator() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.evaluate_selective8_evidence_packet import (
        aggregate_rows,
        score_trial,
    )

    rows = [
        score_trial(_trial(run_id="complete")),
        score_trial(_trial(run_id="missing", activated=["opentargets-database"])),
        score_trial(_trial(run_id="invalid", validation_passed=False)),
    ]

    summary = aggregate_rows(rows)
    group = summary["groups"]["middleware_plus_governor"]

    assert group["runs"] == 3
    assert group["validation_passed_runs"] == 2
    assert group["mean_required_skill_hit_count"] == 3.0
    assert group["complete_evidence_packet_activation_only_count"] == 2
    assert group["complete_evidence_packet_validated_count"] == 1
    assert group["complete_evidence_packet_validated_rate"] == 1 / 3


def test_evidence_packet_cli_writes_json_jsonl_and_markdown(tmp_path: Path) -> None:
    from docs.benchmarks.hypothesis_generation_consistency.evaluate_selective8_evidence_packet import (
        main,
    )

    report = tmp_path / "hypothesis_report.json"
    report.write_text("{}", encoding="utf-8")
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    (result_dir / "benchmark_results.json").write_text(
        json.dumps({"trials": [_trial(report_path=str(report))]}),
        encoding="utf-8",
    )

    assert main([str(result_dir)]) == 0

    assert (result_dir / "evidence_packet_scores.json").exists()
    assert (result_dir / "evidence_packet_scores.jsonl").exists()
    assert (result_dir / "evidence_packet_scores.md").exists()
    payload = json.loads(
        (result_dir / "evidence_packet_scores.json").read_text(encoding="utf-8")
    )
    assert payload["rows"][0]["complete_evidence_packet_validated"] is True
