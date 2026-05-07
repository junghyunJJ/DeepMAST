#!/usr/bin/env python3
"""Analyze DrugTarget trace variability and stable report fingerprints."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_ISSUE_CODES = {
    "REPORT_EXPANSIONS_INVALID",
    "REPORT_RENDER_NOT_DETERMINISTIC",
    "HYPOTHESIS_SCHEMA_INVALID",
    "FEATURED_GAP_LABEL_DRIFT",
    "FAILED_SUFFIX_LEAK",
    "UNVERIFIED_NUMERIC_PREDICTION",
    "NON_EXPAND_TEMPLATE_MUTATION",
    "MISSING_RENDER_METADATA",
    "RENDER_METADATA_INVALID",
    "RENDER_SOURCE_HASH_MISMATCH",
    "RENDERED_DRUG_MD_HASH_MISMATCH",
    "LEGACY_RENDER_MODE_NOT_ALLOWED",
    "SOURCE_PROVENANCE_MISMATCH",
    "FALSE_ABSENCE_CLAIM",
    "FILENAME_REGISTRY_DRIFT",
    "PAGINATION_CAP_UNACKNOWLEDGED",
    "SOURCE_PATH_PREFIX_MISSING",
}


def analyze_trace_file(trace_path: Path) -> dict[str, Any]:
    text = trace_path.read_text(encoding="utf-8", errors="replace")
    issue_codes = sorted(code for code in _ISSUE_CODES if code in text)
    lower = text.lower()
    return {
        "trace_path": str(trace_path),
        "issue_codes": issue_codes,
        "deterministic_rejection_count": len(re.findall(r"\brejected?\b|blocked", lower)),
        "save_retry_count": len(re.findall(r"save_[a-z_]+", lower)),
        "report_writer_repair_loop_count": lower.count("repair"),
        "failed_suffix_leak_count": text.count("_FAILED"),
        "fabricated_reference_count": len(re.findall(r"\bknown_drugs\.json\b", text)),
        "unverified_prediction_count": text.count("UNVERIFIED_NUMERIC_PREDICTION"),
        "source_provenance_mismatch_count": text.count("SOURCE_PROVENANCE_MISMATCH"),
        "false_absence_claim_count": text.count("FALSE_ABSENCE_CLAIM"),
        "filename_registry_drift_count": text.count("FILENAME_REGISTRY_DRIFT"),
        "pagination_cap_warning_count": text.count("PAGINATION_CAP_UNACKNOWLEDGED"),
        "final_pass": "valid=true" in lower or '"valid": true' in lower,
    }


def extract_drug_md_structural_fingerprint(data_dir: Path) -> dict[str, Any]:
    drug_md = data_dir / "drug.md"
    text = drug_md.read_text(encoding="utf-8", errors="replace") if drug_md.exists() else ""
    featured_genes = sorted(set(re.findall(r"- \*\*([A-Za-z0-9-]+)\*\* — Classification:", text)))
    categories: dict[str, int] = {}
    for category in re.findall(r"\*\*Category:\*\*\s*([^\n]+)", text):
        category = category.strip()
        categories[category] = categories.get(category, 0) + 1
    citations = sorted(set(re.findall(r"\b[\w.-]+\.json\b", text)))
    warnings: list[str] = []
    render_path = data_dir / "drug_report_render.json"
    if render_path.exists():
        try:
            render = json.loads(render_path.read_text(encoding="utf-8"))
            raw = render.get("pagination_warnings", [])
            if isinstance(raw, list):
                warnings = [str(item) for item in raw]
        except Exception:
            warnings = []
    return {
        "featured_genes": featured_genes,
        "hypothesis_count_by_category": categories,
        "citation_files": citations,
        "pagination_warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+", type=Path)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()

    report = {"traces": [analyze_trace_file(path) for path in args.traces]}
    if args.data_dir:
        report["fingerprint"] = extract_drug_md_structural_fingerprint(args.data_dir)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
