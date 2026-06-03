"""Schema-aware hypothesis_report.json canonicalization and persistence."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from src.agents.drug_target.tools.hypothesis_grounding import validate_hypothesis_grounding

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
REQUIRED_HYPOTHESIS_CATEGORIES = set(_CATEGORIES)
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


def _canonical_reference_detail(
    ref: Any,
    evidence_dir: Path,
    *,
    allow_failed_marker_contrast: bool,
) -> dict | None:
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
        usage = "contrast" if failed_marker and allow_failed_marker_contrast else "primary"
    display_reference = filename
    if failed_marker and usage != "contrast":
        display_reference = f"{filename}_FAILED"
    return {
        "filename": filename,
        "usage": usage,
        "stage1_pair_status": status,
        "display_reference": display_reference,
    }


def _clean_contrast_reference(ref: Any) -> str | None:
    display = str(ref).strip()
    if not display:
        return None
    match = _JSON_REF_RE.search(display)
    if not match:
        return None
    return match.group(1)


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
        if isinstance(category, str):
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
        existing_contrast = [
            cleaned
            for ref in hyp.get("contrast_references", [])
            if (cleaned := _clean_contrast_reference(ref)) is not None
        ]

        raw_details = hyp.get("evidence_reference_details")
        allow_failed_marker_contrast = isinstance(raw_details, list)
        if not allow_failed_marker_contrast:
            raw_details = hyp.get("evidence_references", [])
        if not isinstance(raw_details, list):
            raw_details = []
        details = [
            detail
            for ref in raw_details
            if (
                detail := _canonical_reference_detail(
                    ref,
                    evidence_dir,
                    allow_failed_marker_contrast=allow_failed_marker_contrast,
                )
            )
            is not None
        ]
        hyp["evidence_reference_details"] = details
        hyp["evidence_references"] = [
            d["display_reference"]
            for d in details
            if d["usage"] != "contrast"
        ]
        contrast = [
            d["display_reference"]
            for d in details
            if d["usage"] == "contrast" and d["display_reference"] not in existing_contrast
        ]
        hyp["contrast_references"] = existing_contrast + contrast

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
        _tag_hypothesis_prediction_grounding,
        _validate_hypothesis_report_references,
        _validate_hypothesis_report_topn_and_failed_pairs,
    )

    diag = _validate_hypothesis_report_topn_and_failed_pairs(canonical, evidence_dir)
    canonical["evidence_coverage_pct"] = diag["evidence_coverage_pct"]
    canonical["topn_coverage"] = diag["topn_coverage"]
    canonical["gap_analysis"] = diag["gap_analysis"]

    ref_errors = _validate_hypothesis_report_references(canonical, evidence_dir)
    if ref_errors:
        result["errors"].extend(ref_errors)
        result["topn_coverage"] = diag["topn_coverage"]
        result["failed_pair_violations"] = diag["failed_pair_violations"]
        return result

    grounding_errors = validate_hypothesis_grounding(canonical, evidence_dir)
    if grounding_errors:
        result["errors"].extend(grounding_errors)
        result["topn_coverage"] = diag["topn_coverage"]
        result["failed_pair_violations"] = diag["failed_pair_violations"]
        result["hypothesis_grounding_violations"] = grounding_errors
        return result

    if diag["reject_reason"]:
        result["errors"].append(diag["reject_reason"])
        result["topn_coverage"] = diag["topn_coverage"]
        result["failed_pair_violations"] = diag["failed_pair_violations"]
        return result

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


def _quality_error(code: str, message: str, **details: Any) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if details:
        err["details"] = details
    return err


def validate_hypothesis_report_quality(
    data_dir: str | Path,
    *,
    run_started_at: float | None = None,
    min_hypotheses: int = 4,
    max_hypotheses: int = 6,
) -> dict:
    """Validate a saved hypothesis report for graph-level finalization gating."""
    base = Path(data_dir).expanduser().resolve()
    evidence_dir = base / "evidence"
    path = evidence_dir / "hypothesis_report.json"
    result: dict = {
        "valid": False,
        "errors": [],
        "warnings": [],
        "path": str(path),
        "hypothesis_count": None,
        "category_coverage": {
            "required": sorted(REQUIRED_HYPOTHESIS_CATEGORIES),
            "present": [],
            "missing": sorted(REQUIRED_HYPOTHESIS_CATEGORIES),
        },
        "topn_coverage": None,
        "evidence_coverage_pct": None,
    }

    if not path.exists():
        result["errors"].append(
            _quality_error(
                "HYPOTHESIS_REPORT_MISSING",
                "evidence/hypothesis_report.json is missing.",
            )
        )
        return result

    try:
        mtime = path.stat().st_mtime
    except OSError as exc:
        result["errors"].append(
            _quality_error(
                "HYPOTHESIS_REPORT_STAT_FAILED",
                f"Could not inspect hypothesis_report.json: {exc}",
            )
        )
        return result
    if run_started_at is not None and mtime < run_started_at:
        result["errors"].append(
            _quality_error(
                "HYPOTHESIS_REPORT_STALE",
                "hypothesis_report.json predates the current graph run.",
                report_mtime=mtime,
                run_started_at=run_started_at,
            )
        )
        return result

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["errors"].append(
            _quality_error(
                "HYPOTHESIS_REPORT_INVALID_JSON",
                f"hypothesis_report.json is not valid JSON: {exc}",
            )
        )
        return result

    canonical, errors, diagnostics = canonicalize_hypothesis_report(
        raw,
        evidence_dir,
        legacy_compat=False,
    )
    result["warnings"].extend(diagnostics)
    if canonical is None:
        result["errors"].append(
            _quality_error(
                "SCHEMA_VALIDATION_FAILED",
                "; ".join(errors) or "hypothesis_report.json failed schema validation.",
                errors=errors,
            )
        )
        return result
    if errors:
        result["errors"].append(
            _quality_error(
                "SCHEMA_VALIDATION_FAILED",
                "; ".join(errors),
                errors=errors,
            )
        )

    from src.agents.drug_target.tools.evidence_loader import (
        _tag_hypothesis_prediction_grounding,
        _validate_hypothesis_report_references,
        _validate_hypothesis_report_topn_and_failed_pairs,
    )

    hypotheses = canonical.get("hypotheses", [])
    hypothesis_count = len(hypotheses) if isinstance(hypotheses, list) else 0
    result["hypothesis_count"] = hypothesis_count
    if hypothesis_count < min_hypotheses or hypothesis_count > max_hypotheses:
        result["errors"].append(
            _quality_error(
                "HYPOTHESIS_COUNT_OUT_OF_RANGE",
                f"Expected {min_hypotheses}-{max_hypotheses} hypotheses, found {hypothesis_count}.",
                min=min_hypotheses,
                max=max_hypotheses,
                found=hypothesis_count,
            )
        )

    present_categories: set[str] = set()
    for hyp in hypotheses:
        if not isinstance(hyp, dict):
            continue
        category = hyp.get("category")
        if isinstance(category, str) and category in REQUIRED_HYPOTHESIS_CATEGORIES:
            present_categories.add(category)
    missing_categories = sorted(REQUIRED_HYPOTHESIS_CATEGORIES - present_categories)
    result["category_coverage"] = {
        "required": sorted(REQUIRED_HYPOTHESIS_CATEGORIES),
        "present": sorted(present_categories),
        "missing": missing_categories,
    }
    if missing_categories:
        result["errors"].append(
            _quality_error(
                "MISSING_REQUIRED_CATEGORIES",
                "Hypothesis report is missing required thematic categories.",
                missing=missing_categories,
            )
        )

    diag = _validate_hypothesis_report_topn_and_failed_pairs(canonical, evidence_dir)
    result["topn_coverage"] = diag["topn_coverage"]
    result["evidence_coverage_pct"] = diag["evidence_coverage_pct"]
    ref_errors = _validate_hypothesis_report_references(canonical, evidence_dir)
    if ref_errors:
        result["errors"].append(
            _quality_error(
                "INVALID_EVIDENCE_REFERENCES",
                "; ".join(ref_errors),
                errors=ref_errors,
            )
        )
    grounding_errors = validate_hypothesis_grounding(canonical, evidence_dir)
    result["hypothesis_grounding_violations"] = grounding_errors
    if grounding_errors:
        result["errors"].append(
            _quality_error(
                "HYPOTHESIS_GROUNDING_VIOLATION",
                "; ".join(grounding_errors),
                errors=grounding_errors,
            )
        )
    if diag["failed_pair_violations"]:
        result["errors"].append(
            _quality_error(
                "FAILED_PAIR_VIOLATION",
                "; ".join(diag["failed_pair_violations"]),
                errors=diag["failed_pair_violations"],
            )
        )
    if diag["reject_reason"]:
        result["errors"].append(
            _quality_error(
                "TOPN_COVERAGE_MISSING",
                diag["reject_reason"],
                topn_coverage=diag["topn_coverage"],
            )
        )

    grounding = _tag_hypothesis_prediction_grounding(canonical, evidence_dir=evidence_dir)
    result["prediction_grounding_summary"] = grounding
    if grounding.get("unverified", 0) > 0:
        result["errors"].append(
            _quality_error(
                "UNVERIFIED_NUMERIC_PREDICTION",
                "One or more falsifiable predictions contain unverified numeric values.",
                unverified_indices=grounding.get("unverified_indices", []),
            )
        )

    result["valid"] = not result["errors"]
    return result


@tool
def save_hypothesis_report(data_dir: str, report: dict) -> str:
    """Save canonical schema-validated evidence/hypothesis_report.json."""
    return json.dumps(persist_hypothesis_report(data_dir, report), indent=2)
