from __future__ import annotations

from pathlib import Path

from scripts import diagnose_drug_target_run as diag


def _clean_artifacts() -> dict:
    return {
        "evidence_dir_exists": True,
        "evidence_file_count": 3,
        "stage1_pair_files": [],
        "ot_gene_files": [],
        "stage3_gene_files": [],
        "missing_required": [],
        "missing_root_files": [],
    }


def _clean_drug_md() -> dict:
    return {
        "exists": True,
        "char_count": 100,
        "line_count": 10,
        "hypothesis_section_present": True,
        "hypothesis_section_empty": False,
        "unexpanded_placeholder_count": 0,
        "unexpanded_samples": [],
    }


def _clean_refs() -> dict:
    return {
        "hypothesis_report_exists": True,
        "hypothesis_count": 1,
        "cited_reference_count": 1,
        "missing_references": [],
        "missing_reference_count": 0,
    }


def test_render_markdown_reports_issues_when_hist_max_exceeds_30(tmp_path: Path) -> None:
    trace_stats = {
        "trace_path": str(tmp_path / "trace.log"),
        "subagent_events": {},
        "sequential_thinking_calls": 1,
        "thought_number_samples": 1,
        "longest_thought_stagnation": 0,
        "thought_history_max": 31,
        "tool_counts": {},
        "fixup_markers": [],
    }

    report = diag.render_markdown(
        tmp_path,
        trace_stats,
        _clean_artifacts(),
        _clean_drug_md(),
        _clean_refs(),
    )

    assert "DEGENERATE LOOP SIGNATURE" in report
    assert "Clean run" not in report
    assert "degenerate sequential_thinking loop" in report


def test_render_markdown_reports_recovered_fixup_as_warning(tmp_path: Path) -> None:
    trace_stats = {
        "trace_path": str(tmp_path / "trace.log"),
        "subagent_events": {},
        "sequential_thinking_calls": 0,
        "thought_number_samples": 0,
        "longest_thought_stagnation": 0,
        "thought_history_max": 0,
        "tool_counts": {},
        "fixup_markers": ["[HYPOTHESIS-FIXUP] SUCCESS - hypothesis_report.json now present"],
    }

    report = diag.render_markdown(
        tmp_path,
        trace_stats,
        _clean_artifacts(),
        _clean_drug_md(),
        _clean_refs(),
    )

    assert "Clean run" not in report
    assert "WARNINGS" in report
    assert "recovered fixup markers" in report
