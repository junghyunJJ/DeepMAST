from __future__ import annotations

import json
from pathlib import Path


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "pair_id": "16",
        "sequence": "AB",
        "arm": "on",
        "data_dir": "",
        "generation_status": "passed",
        "generation_seconds": 10.0,
        "report_complete": True,
        "status": "evaluated",
        "complete": True,
        "usable": True,
        "hard_error_count": 0,
        "evaluation_complete": True,
        "issues": [],
        "elapsed_seconds": 1.0,
        "hashes_before": {},
        "hashes_after": {},
    }
    row.update(overrides)
    return row


def test_write_comparison_keeps_planned_denominator_and_unknown_bounds(tmp_path: Path) -> None:
    from scripts.summarize_sni_guardrail_recovery import write_comparison

    result = write_comparison(
        tmp_path,
        [
            _row(arm="on", usable=True),
            _row(arm="on", sequence="BA", status="evaluation_failed", usable=None, evaluation_complete=False),
            _row(arm="off", usable=False, hard_error_count=1),
        ],
    )

    assert result["summary"]["on"]["planned"] == 20
    assert result["summary"]["on"]["passed"] == 1
    assert result["summary"]["on"]["unknown"] == 19
    assert result["summary"]["on"]["pass_bounds"] == {"lower": "1/20", "upper": "20/20", "kind": "known bounds, not CI"}
    assert result["summary"]["off"]["passed"] == 0
    assert result["summary"]["off"]["failed"] == 1
    assert "1/20 to 20/20" in (tmp_path / "comparison.md").read_text(encoding="utf-8")


def test_write_comparison_counts_known_hard_errors_even_when_evaluation_incomplete(tmp_path: Path) -> None:
    from scripts.summarize_sni_guardrail_recovery import write_comparison

    result = write_comparison(
        tmp_path,
        [
            _row(
                status="evaluation_failed",
                usable=None,
                hard_error_count=2,
                evaluation_complete=False,
                issues=[{"severity": "error", "code": "unsupported_claim"}],
            )
        ],
    )

    summary = result["summary"]["on"]
    assert summary["failed"] == 1
    assert summary["unknown"] == 19
    assert summary["invalid_output"] == {"count": 1, "denominator": 20, "rate": 0.05}
    assert result["known_error_codes"] == {"on": {"unsupported_claim": 1}, "off": {}}


def test_write_comparison_treats_complete_missing_rag_audit_as_audit_gap(tmp_path: Path) -> None:
    from scripts.summarize_sni_guardrail_recovery import REQUIRED_REPORT_FILES, write_comparison

    data_dir = tmp_path / "run"
    data_dir.mkdir()
    for name in REQUIRED_REPORT_FILES:
        (data_dir / name).write_text("ok\n", encoding="utf-8")
    (data_dir / "run_manifest.json").write_text(
        json.dumps({"error": {"message": "missing RAG audit: run/rag_audit.jsonl"}}),
        encoding="utf-8",
    )

    result = write_comparison(
        tmp_path / "out",
        [
            _row(
                arm="off",
                data_dir=str(data_dir),
                generation_status="failed",
                generation_classification=None,
                report_complete=None,
            )
        ],
    )

    summary = result["summary"]["off"]
    assert summary["generation_classification"] == {"completed": 1}
    assert summary["audit_gap_count"] == 1
    assert summary["blocked"] == 0
    assert result["rows"][0]["physical_stages"] == {
        "part1": True,
        "part2": True,
        "part3": True,
        "synthesis": True,
        "html": True,
    }


def test_write_comparison_reads_guardrail_result_correction_counts(tmp_path: Path) -> None:
    from scripts.summarize_sni_guardrail_recovery import write_comparison

    data_dir = tmp_path / "run"
    data_dir.mkdir()
    (data_dir / "parts_guardrail_result.json").write_text(
        json.dumps(
            {
                "deterministic_initial_error_count": 2,
                "semantic_initial_error_count": 3,
                "initial_error_count": 99,
                "final_error_count": 1,
                "repair_attempt_count": 4,
                "terminal_repair_count": 1,
                "changed_sections": 5,
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "synthesis_guardrail_result.json").write_text(
        json.dumps(
            {
                "deterministic_initial_error_count": 7,
                "semantic_initial_error_count": 11,
                "final_error_count": 0,
                "repair_attempt_count": 13,
                "terminal_repair_count": 2,
                "changed_claims": 6,
            }
        ),
        encoding="utf-8",
    )
    for subdir, suffix in (("before", "old"), ("after", "new")):
        directory = data_dir / subdir
        directory.mkdir()
        (directory / "part1_final.md").write_text("same\n", encoding="utf-8")
        (directory / "part2_final.md").write_text(f"{suffix}\n", encoding="utf-8")

    result = write_comparison(
        tmp_path,
        [
            _row(
                arm="on",
                data_dir=str(data_dir),
                correction_counts={
                    "initial_errors": 1000,
                    "normal_repairs": 1000,
                },
            )
        ],
    )

    assert result["corrections"]["on"] == {
        "deterministic_initial_errors": 9,
        "semantic_initial_errors": 14,
        "initial_errors": 23,
        "final_errors": 1,
        "released_initial_errors": 23,
        "historic_final_errors": 1,
        "normal_repairs": 17,
        "terminal_repairs": 3,
        "changed_sections": 5,
        "changed_claims": 6,
        "before_after_md_pairs": 2,
        "before_after_md_pairs_differ": 1,
    }


def test_write_comparison_reads_nested_evaluation_complete_and_excludes_operational_error_codes(tmp_path: Path) -> None:
    from scripts.summarize_sni_guardrail_recovery import write_comparison

    result = write_comparison(
        tmp_path,
        [
            _row(
                status="pending",
                evaluation_complete=None,
                evaluation={
                    "status": "evaluation_failed",
                    "usable": None,
                    "evaluation_complete": False,
                    "issues": [
                        {"severity": "error", "code": "missing_required_artifact"},
                        {"severity": "error", "code": "claim_evaluation_incomplete"},
                        {"severity": "error", "code": "unsupported_claim"},
                    ],
                },
            )
        ],
    )

    assert result["rows"][0]["evaluation_complete"] is False
    assert result["known_error_codes"] == {"on": {"unsupported_claim": 1}, "off": {}}


def test_write_comparison_current_real_rows_recomputes_audited_on_counts(tmp_path: Path) -> None:
    from scripts.summarize_sni_guardrail_recovery import write_comparison

    root = Path("res/deep_interpreter/bc/sni_repair_ablation/guardrail_on_off_20260905T154030Z")
    if not (root / "status.json").exists():
        return

    rows = json.loads((root / "status.json").read_text(encoding="utf-8"))["runs"]
    result = write_comparison(tmp_path, rows)

    assert result["corrections"]["on"] == {
        "deterministic_initial_errors": 189,
        "semantic_initial_errors": 152,
        "initial_errors": 341,
        "final_errors": 2,
        "released_initial_errors": 305,
        "historic_final_errors": 0,
        "normal_repairs": 61,
        "terminal_repairs": 5,
        "changed_sections": 339,
        "changed_claims": 23,
        "before_after_md_pairs": 78,
        "before_after_md_pairs_differ": 58,
    }
    assert sorted(path.name for path in tmp_path.iterdir()) == ["comparison.csv", "comparison.json", "comparison.md"]
