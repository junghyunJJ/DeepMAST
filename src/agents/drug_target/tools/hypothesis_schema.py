"""Schema-aware hypothesis_report.json canonicalization and persistence."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

_SCHEMA_VERSION = "hypothesis_report.v2"
_SCORE_KEYS = (
    "evidence_coverage",
    "specificity",
    "novelty",
    "actionability",
    "composite",
)
_ENTITY_KEYS = ("genes", "pathways", "cell_types", "drugs")
_CATEGORY_ALIASES = {
    "MoA": "Mechanism of Action",
    "MOA": "Mechanism of Action",
}
_CATEGORIES = {
    "Mechanism of Action",
    "Therapeutic Strategy",
    "Cross-Target Interaction",
    "Novel Pathway",
}
_GAP_PREFIX_RE = re.compile(r"^\s*(\[(?:FEATURED-GAP|GAP)\])\s*(.*)$")
_JSON_REF_RE = re.compile(r"([A-Za-z0-9_.\-]+\.json)(?:_FAILED)?")
_STAGE1_REF_RE = re.compile(r"^stage1_([A-Za-z0-9-]+)--([A-Za-z0-9-]+)\.json$")


def _parse_report(report: Any) -> tuple[dict | None, list[str]]:
    if isinstance(report, dict):
        return copy.deepcopy(report), []
    if isinstance(report, str):
        try:
            parsed = json.loads(report)
        except json.JSONDecodeError as exc:
            return None, [f"report is not valid JSON: {exc}"]
        if isinstance(parsed, dict):
            return parsed, []
    return None, ["report must be a JSON object"]


def _stage1_status(filename: str, evidence_dir: Path) -> str:
    match = _STAGE1_REF_RE.match(filename)
    if not match:
        return "not_stage1"
    try:
        from src.agents.drug_target.tools.evidence_loader import (
            _load_stage1_filter_results,
        )

        results = _load_stage1_filter_results(evidence_dir)
    except Exception:
        return "unknown"
    pair_key = f"{match.group(1).upper()}--{match.group(2).upper()}"
    passed = results.get(pair_key)
    if passed is True:
        return "passed"
    if passed is False:
        return "failed"
    return "unknown"


def _canonical_gap_type(title: str, explicit: str | None) -> tuple[str, str, str | None]:
    label = None
    clean_title = title.strip()
    match = _GAP_PREFIX_RE.match(clean_title)
    if match:
        label = match.group(1)
        clean_title = match.group(2).strip()
    if explicit in {"none", "orphan_evidence", "featured_coverage"}:
        gap_type = explicit
    elif label == "[FEATURED-GAP]":
        gap_type = "featured_coverage"
    elif label == "[GAP]":
        gap_type = "orphan_evidence"
    else:
        gap_type = "none"
    return clean_title, gap_type, label


def _canonical_entities(raw: Any) -> dict[str, list[str]]:
    entities = raw if isinstance(raw, dict) else {}
    out: dict[str, list[str]] = {}
    for key in _ENTITY_KEYS:
        values = entities.get(key, [])
        if not isinstance(values, list):
            values = []
        cleaned = [str(v).strip() for v in values if str(v).strip()]
        if key == "genes":
            cleaned = [v.upper() for v in cleaned]
        out[key] = cleaned
    return out


def _canonical_reference_detail(ref: Any, evidence_dir: Path) -> dict | None:
    if isinstance(ref, dict):
        display = str(ref.get("display_reference") or ref.get("filename") or "").strip()
        usage = ref.get("usage")
    else:
        display = str(ref).strip()
        usage = None
    if not display:
        return None
    match = _JSON_REF_RE.search(display)
    if not match:
        return None
    filename = match.group(1)
    failed_marker = ".json_FAILED" in display
    status = _stage1_status(filename, evidence_dir)
    if usage not in {"primary", "supporting", "contrast"}:
        usage = "contrast" if failed_marker else "primary"
    detail_display = f"{filename}_FAILED" if usage == "contrast" and status == "failed" else filename
    return {
        "filename": filename,
        "usage": usage,
        "stage1_pair_status": status,
        "display_reference": detail_display,
    }


def _validate_scores(hyp: dict, *, strict: bool, errors: list[str], index: int) -> dict:
    raw = hyp.get("scores")
    if not isinstance(raw, dict):
        raw = {}
    scores: dict[str, float | None] = {}
    for key in _SCORE_KEYS:
        value = raw.get(key)
        if isinstance(value, bool):
            value = None
        if isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0:
            scores[key] = float(value)
            continue
        if strict:
            errors.append(f"hypotheses[{index}].scores.{key} must be a number in [0.0, 1.0]")
        scores[key] = None
    return scores


def canonicalize_hypothesis_report(
    report: Any,
    evidence_dir: Path,
    *,
    legacy_compat: bool = True,
) -> tuple[dict | None, list[str], list[dict]]:
    """Return a canonical v2 report, validation errors, and diagnostics."""
    parsed, errors = _parse_report(report)
    diagnostics: list[dict] = []
    if parsed is None:
        return None, errors, diagnostics

    canonical = copy.deepcopy(parsed)
    canonical["schema_version"] = _SCHEMA_VERSION

    hypotheses = canonical.get("hypotheses")
    if not isinstance(hypotheses, list):
        return None, ["hypotheses must be a list"], diagnostics

    for idx, hyp in enumerate(hypotheses):
        if not isinstance(hyp, dict):
            errors.append(f"hypotheses[{idx}] must be an object")
            continue

        title, gap_type, label = _canonical_gap_type(
            str(hyp.get("title") or hyp.get("hypothesis") or ""),
            hyp.get("gap_type"),
        )
        hyp["title"] = title
        hyp["gap_type"] = gap_type
        if label:
            hyp["legacy_title_prefix"] = label

        category = hyp.get("category")
        category = _CATEGORY_ALIASES.get(category, category)
        if category not in _CATEGORIES:
            if legacy_compat:
                category = "Mechanism of Action"
                diagnostics.append({
                    "code": "LEGACY_CATEGORY_DEFAULTED",
                    "hypothesis_index": idx,
                })
            else:
                errors.append(f"hypotheses[{idx}].category is not canonical")
        hyp["category"] = category

        hyp["biological_entities"] = _canonical_entities(hyp.get("biological_entities"))
        hyp["scores"] = _validate_scores(hyp, strict=not legacy_compat, errors=errors, index=idx)
        hyp.setdefault("contrast_references", [])

        raw_details = hyp.get("evidence_reference_details")
        if not isinstance(raw_details, list):
            raw_details = hyp.get("evidence_references", [])
        if not isinstance(raw_details, list):
            raw_details = []
        details = [
            detail
            for ref in raw_details
            if (detail := _canonical_reference_detail(ref, evidence_dir)) is not None
        ]
        hyp["evidence_reference_details"] = details
        hyp["evidence_references"] = [d["display_reference"] for d in details]
        contrast = [
            d["display_reference"]
            for d in details
            if d["usage"] == "contrast" and d["display_reference"] not in hyp["contrast_references"]
        ]
        hyp["contrast_references"] = list(hyp["contrast_references"]) + contrast

    gap_analysis = canonical.get("gap_analysis")
    if not isinstance(gap_analysis, dict):
        gap_analysis = {}
        canonical["gap_analysis"] = gap_analysis
    orphans = gap_analysis.get("orphan_files", [])
    if not isinstance(orphans, list):
        orphans = []
    gap_analysis["orphan_files"] = [
        entry[:-len("_FAILED")] if isinstance(entry, str) and entry.endswith("_FAILED") else entry
        for entry in orphans
    ]
    gap_analysis.setdefault("total_evidence_files", 0)
    gap_analysis.setdefault("referenced_files", 0)

    return canonical, errors, diagnostics


def persist_hypothesis_report(data_dir: str | Path, report: Any) -> dict:
    """Validate, canonicalize, and write evidence/hypothesis_report.json."""
    base = Path(data_dir).expanduser().resolve()
    evidence_dir = base / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    parsed, _ = _parse_report(report)
    legacy_compat = not (
        isinstance(parsed, dict) and parsed.get("schema_version") == _SCHEMA_VERSION
    )
    canonical, errors, diagnostics = canonicalize_hypothesis_report(
        report,
        evidence_dir,
        legacy_compat=legacy_compat,
    )
    result = {
        "saved": False,
        "path": str(evidence_dir / "hypothesis_report.json"),
        "errors": errors,
        "diagnostics": diagnostics,
    }
    if canonical is None:
        return result

    from src.agents.drug_target.tools.evidence_loader import (
        _sanitize_gap_analysis,
        _tag_hypothesis_prediction_grounding,
        _validate_hypothesis_report_references,
        _validate_hypothesis_report_topn_and_failed_pairs,
    )

    ref_errors = _validate_hypothesis_report_references(canonical, evidence_dir)
    if ref_errors:
        result["errors"].extend(ref_errors)
        return result

    diag = _validate_hypothesis_report_topn_and_failed_pairs(canonical, evidence_dir)
    canonical["evidence_coverage_pct"] = diag["evidence_coverage_pct"]
    canonical["topn_coverage"] = diag["topn_coverage"]
    if diag["reject_reason"]:
        result["errors"].append(diag["reject_reason"])
        result["topn_coverage"] = diag["topn_coverage"]
        result["failed_pair_violations"] = diag["failed_pair_violations"]
        return result

    _sanitize_gap_analysis(canonical, evidence_dir)
    canonical["prediction_grounding_summary"] = _tag_hypothesis_prediction_grounding(
        canonical,
        evidence_dir=evidence_dir,
    )

    if result["errors"]:
        return result

    path = evidence_dir / "hypothesis_report.json"
    path.write_text(json.dumps(canonical, indent=2, ensure_ascii=False), encoding="utf-8")
    result["saved"] = True
    result["diagnostics"] = diagnostics
    return result


@tool
def save_hypothesis_report(data_dir: str, report: dict) -> str:
    """Save canonical schema-validated evidence/hypothesis_report.json."""
    return json.dumps(persist_hypothesis_report(data_dir, report), indent=2)
