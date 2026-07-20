from __future__ import annotations

import json
from pathlib import Path

from src.agents.deep_interpreter.synthesis_consistency_validation import (
    repair_synthesis_consistency,
    validate_synthesis_consistency,
)


def _write_base_sources(tmp_path: Path) -> None:
    (tmp_path / "part4_candidate_selection.json").write_text(
        json.dumps(
            {
                "selected_genes": ["ERBB3", "ERBB2"],
                "selected_lr_pairs": [
                    {"interaction": "CDH1^ERBB3", "combinedscore": 0.8141}
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "part4_therapeutic_synthesis.md").write_text(
        "### 1. Candidate: ERBB3\n"
        "- Score profile: combined 16 = validated 10 + exploratory 6.\n",
        encoding="utf-8",
    )
    (tmp_path / "part2_final.md").write_text(
        "### Quantitative Findings\nFactor3 estrogen enrichment estimate = -5.480.\n",
        encoding="utf-8",
    )


def test_validator_reports_repairable_canonical_fact_mismatches(
    tmp_path: Path,
) -> None:
    _write_base_sources(tmp_path)
    (tmp_path / "synthesis.md").write_text(
        "### 1. ERBB3 (Combined Score: 15)\n"
        "CDH1-ERBB3 combinedscore = 0.7000.\n"
        "Factor3 estrogen enrichment estimate = -4.200.\n",
        encoding="utf-8",
    )

    result = validate_synthesis_consistency(tmp_path)

    errors = [issue for issue in result["issues"] if issue["severity"] == "error"]
    assert [issue["code"] for issue in errors] == [
        "synthesis_consistency_score_mismatch",
        "synthesis_consistency_lr_mismatch",
        "synthesis_consistency_quantitative_mismatch",
    ]
    assert [issue["replacement"] for issue in errors] == ["16", "0.8141", "-5.480"]
    assert all(issue["repairable"] is True for issue in errors)
    assert {item["canonical_value"] for item in result["results"]} >= {
        "16",
        "0.8141",
        "-5.480",
    }


def test_repair_replaces_only_literal_source_derived_values(tmp_path: Path) -> None:
    _write_base_sources(tmp_path)
    (tmp_path / "synthesis.md").write_text(
        "### 1. ERBB3 (Combined Score: 15)\n"
        "CDH1-ERBB3 combinedscore = 0.7000.\n"
        "Factor3 estrogen enrichment estimate = -4.200.\n",
        encoding="utf-8",
    )
    issues = validate_synthesis_consistency(tmp_path)["issues"]

    changed = repair_synthesis_consistency(tmp_path, issues)

    assert changed == 3
    assert (tmp_path / "synthesis.md").read_text(encoding="utf-8") == (
        "### 1. ERBB3 (Combined Score: 16)\n"
        "CDH1-ERBB3 combinedscore = 0.8141.\n"
        "Factor3 estrogen enrichment estimate = -5.480.\n"
    )


def test_unselected_candidate_and_lr_pair_are_unrepairable(tmp_path: Path) -> None:
    _write_base_sources(tmp_path)
    (tmp_path / "synthesis.md").write_text(
        "### 1. EGFR (Combined Score: 15)\n"
        "AREG-EGFR combinedscore = 0.7000.\n",
        encoding="utf-8",
    )

    issues = validate_synthesis_consistency(tmp_path)["issues"]

    assert [issue["code"] for issue in issues] == [
        "synthesis_consistency_unresolved",
        "synthesis_consistency_unresolved",
    ]
    assert all(issue["severity"] == "error" for issue in issues)
    assert all(issue["repairable"] is False for issue in issues)


def test_missing_part4_json_warns_without_fabricated_canonical_values(
    tmp_path: Path,
) -> None:
    (tmp_path / "synthesis.md").write_text(
        "### 1. ERBB3 (Combined Score: 15)\n",
        encoding="utf-8",
    )

    result = validate_synthesis_consistency(tmp_path)

    assert result["issues"] == [
        {
            "code": "synthesis_consistency_source_missing",
            "severity": "warning",
            "file": "part4_candidate_selection.json",
            "value": "part4_candidate_selection.json",
            "repairable": False,
        }
    ]
    assert result["results"] == []


def test_malformed_part4_json_warns(tmp_path: Path) -> None:
    (tmp_path / "part4_candidate_selection.json").write_text("{", encoding="utf-8")
    (tmp_path / "synthesis.md").write_text(
        "### 1. ERBB3 (Combined Score: 15)\n",
        encoding="utf-8",
    )

    [issue] = validate_synthesis_consistency(tmp_path)["issues"]

    assert issue["code"] == "synthesis_consistency_source_malformed"
    assert issue["severity"] == "warning"
    assert issue["repairable"] is False


def test_source_text_with_no_explicit_anchor_creates_no_issue(tmp_path: Path) -> None:
    _write_base_sources(tmp_path)
    (tmp_path / "part2_final.md").write_text(
        "Factor3 estrogen enrichment estimate was discussed without an anchor.\n",
        encoding="utf-8",
    )
    (tmp_path / "synthesis.md").write_text(
        "No bounded consistency facts here.\n",
        encoding="utf-8",
    )

    assert validate_synthesis_consistency(tmp_path)["issues"] == []
