from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_drug_target_trace_variability import (
    analyze_trace_file,
    extract_drug_md_structural_fingerprint,
)


def test_trace_variability_parser_extracts_issue_taxonomy(tmp_path: Path) -> None:
    trace = tmp_path / "trace.log"
    trace.write_text(
        "\n".join(
            [
                "save rejected REPORT_EXPANSIONS_INVALID",
                "validator SOURCE_PROVENANCE_MISMATCH",
                "FALSE_ABSENCE_CLAIM in expansion",
                "FILENAME_REGISTRY_DRIFT target_assessment.json",
                "PAGINATION_CAP_UNACKNOWLEDGED",
                "stage1_CD4--ITGB2.json_FAILED leaked",
                "fabricated known_drugs.json citation",
                "finalization valid=false",
            ]
        ),
        encoding="utf-8",
    )

    stats = analyze_trace_file(trace)

    assert stats["deterministic_rejection_count"] == 1
    assert stats["failed_suffix_leak_count"] == 1
    assert stats["fabricated_reference_count"] == 1
    assert stats["issue_codes"] == [
        "FALSE_ABSENCE_CLAIM",
        "FILENAME_REGISTRY_DRIFT",
        "PAGINATION_CAP_UNACKNOWLEDGED",
        "REPORT_EXPANSIONS_INVALID",
        "SOURCE_PROVENANCE_MISMATCH",
    ]
    assert stats["final_pass"] is False


def test_structural_fingerprint_reads_stable_report_facts(tmp_path: Path) -> None:
    (tmp_path / "drug.md").write_text(
        "# Report\n\n"
        "- **CD4** — Classification: validated_target\n"
        "### 4.1. [FEATURED-GAP] CD4 hypothesis\n"
        "**Category:** Mechanism of Action\n"
        "- stage3_CD4.json\n",
        encoding="utf-8",
    )
    (tmp_path / "drug_report_render.json").write_text(
        json.dumps({"pagination_warnings": ["stage3_CD4 capped"]}),
        encoding="utf-8",
    )

    fp = extract_drug_md_structural_fingerprint(tmp_path)

    assert fp["featured_genes"] == ["CD4"]
    assert fp["hypothesis_count_by_category"] == {"Mechanism of Action": 1}
    assert fp["citation_files"] == ["stage3_CD4.json"]
    assert fp["pagination_warnings"] == ["stage3_CD4 capped"]

