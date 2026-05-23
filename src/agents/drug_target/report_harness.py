"""No-LLM harness diagnostics for deterministic drug-target reports."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

from src.agents.drug_target.deterministic_report import finalize_report_mvp
from src.agents.drug_target.evidence_filenames import EvidenceFiles
from src.agents.drug_target.tools.assessment_output import (
    validate_target_assessment_file,
)


HARNESS_SCHEMA_VERSION = "drug_target.report_harness_diagnostics.v1"
HARNESS_DIAGNOSTICS_FILENAME = "report_harness_diagnostics.json"
EXPAND_MARKER_PATTERN = re.compile(r"<!--\s*EXPAND:")
REQUIRED_REPORT_ARTIFACTS = (
    "report_data.json",
    "drug.md",
    "drug_report.html",
    "report_validation.json",
)
OPTIONAL_LEGACY_ARTIFACTS = (
    "report_expansions.json",
    "drug_report_render.json",
    "report_interpretations.json",
)
REQUIRED_EVIDENCE = (
    EvidenceFiles.assessment_results(),
    EvidenceFiles.hypothesis_report(),
)
DEEPAGENTS_ALLOWED_RESPONSIBILITIES = (
    "collect_evidence",
    "write_hypothesis_report",
    "optional_interpretation",
    "orchestration",
    "critique",
    "harness_diagnostics",
)
DEEPAGENTS_FORBIDDEN_RESPONSIBILITIES = (
    "write_report_data",
    "write_drug_md",
    "write_drug_report_html",
    "choose_provenance_keys",
    "decide_final_success",
)
DETERMINISTIC_CODE_OWNS = (
    "report_data_json",
    "drug_md",
    "drug_report_html",
    "report_validation_json",
    "report_harness_diagnostics_json",
    "final_success_or_failure",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _has_expand_marker(text: str) -> bool:
    return bool(EXPAND_MARKER_PATTERN.search(text))


def _artifact_metadata(base: Path, name: str) -> dict[str, Any]:
    path = base / name
    metadata: dict[str, Any] = {
        "path": name,
        "exists": path.exists(),
    }
    if path.exists():
        metadata["size_bytes"] = path.stat().st_size
    return metadata


def _json_metadata(base: Path, name: str) -> dict[str, Any]:
    metadata = _artifact_metadata(base, name)
    if not metadata["exists"]:
        return metadata
    try:
        _read_json(base / name)
    except json.JSONDecodeError as exc:
        metadata["valid_json"] = False
        metadata["json_error"] = str(exc)
    else:
        metadata["valid_json"] = True
    return metadata


def _missing_required_evidence_issues(
    evidence: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for name, metadata in evidence.items():
        if not metadata["exists"]:
            issues.append(
                {
                    "code": "MISSING_REQUIRED_EVIDENCE",
                    "severity": "critical",
                    "message": f"Required evidence file is missing: {name}",
                    "path": name,
                }
            )
            continue
        if metadata.get("valid_json") is False:
            issues.append(
                {
                    "code": "MALFORMED_REQUIRED_EVIDENCE_JSON",
                    "severity": "critical",
                    "message": f"Required evidence file is not valid JSON: {name}",
                    "path": name,
                    "error": metadata.get("json_error"),
                }
            )
    return issues


def _artifact_issues(
    base: Path,
    artifacts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for name, metadata in artifacts.items():
        if not metadata["exists"]:
            issues.append(
                {
                    "code": "MISSING_REQUIRED_ARTIFACT",
                    "severity": "critical",
                    "message": f"Required report artifact is missing: {name}",
                    "path": name,
                }
            )
            continue
        if metadata.get("valid_json") is False:
            issues.append(
                {
                    "code": "MALFORMED_ARTIFACT_JSON",
                    "severity": "critical",
                    "message": f"Report artifact is not valid JSON: {name}",
                    "path": name,
                    "error": metadata.get("json_error"),
                }
            )
    for name in ("drug.md", "drug_report.html"):
        path = base / name
        if path.exists() and _has_expand_marker(path.read_text(encoding="utf-8")):
            issues.append(
                {
                    "code": "UNEXPANDED_PLACEHOLDER",
                    "severity": "critical",
                    "message": f"{name} contains an EXPAND marker",
                    "path": name,
                }
            )
    return issues


def _report_validation_issues(base: Path) -> list[dict[str, Any]]:
    path = base / "report_validation.json"
    if not path.exists():
        return []
    try:
        payload = _read_json(path)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict) or payload.get("valid") is not False:
        return []
    nested_issues = payload.get("issues")
    issue_count = len(nested_issues) if isinstance(nested_issues, list) else 0
    return [
        {
            "code": "REPORT_VALIDATION_FAILED",
            "severity": "critical",
            "message": "report_validation.json marked the deterministic report invalid",
            "path": "report_validation.json",
            "issue_count": issue_count,
        }
    ]


def _artifact_validity_check(
    artifacts: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    artifact_issue_codes = {
        "MISSING_REQUIRED_ARTIFACT",
        "MALFORMED_ARTIFACT_JSON",
        "UNEXPANDED_PLACEHOLDER",
        "REPORT_VALIDATION_FAILED",
    }
    relevant_issues = [
        issue
        for issue in issues
        if issue.get("code") in artifact_issue_codes
    ]
    return {
        "status": "fail" if relevant_issues else "pass",
        "required_artifacts": artifacts,
        "issue_count": len(relevant_issues),
    }


def _source_consistency_check(
    base: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report_data_path = base / "report_data.json"
    if not report_data_path.exists():
        return (
            {
                "status": "skipped",
                "reason": "report_data.json is missing",
                "sources": {},
            },
            [],
        )
    try:
        report_data = _read_json(report_data_path)
    except json.JSONDecodeError:
        return (
            {
                "status": "skipped",
                "reason": "report_data.json is malformed",
                "sources": {},
            },
            [],
        )
    sources = report_data.get("sources") if isinstance(report_data, dict) else None
    if not isinstance(sources, dict):
        issue = {
            "code": "REPORT_DATA_SOURCES_INVALID",
            "severity": "critical",
            "message": "report_data.json sources must be an object",
            "path": "report_data.json",
        }
        return (
            {
                "status": "fail",
                "sources": {},
                "issue_count": 1,
            },
            [issue],
        )

    checked_sources: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    for source, metadata in sources.items():
        source_name = str(source)
        expected_sha256 = (
            metadata.get("sha256") if isinstance(metadata, dict) else None
        )
        source_metadata: dict[str, Any] = {
            "path": source_name,
            "exists": False,
            "expected_sha256": expected_sha256,
        }
        path = base / source_name
        if not isinstance(metadata, dict) or not isinstance(expected_sha256, str):
            issues.append(
                {
                    "code": "REPORT_DATA_SOURCES_INVALID",
                    "severity": "critical",
                    "message": (
                        "report_data.json source entries must include a sha256 string"
                    ),
                    "path": "report_data.json",
                    "source": source_name,
                }
            )
            checked_sources[source_name] = source_metadata
            continue
        if not path.exists():
            issues.append(
                {
                    "code": "MISSING_DECLARED_SOURCE",
                    "severity": "critical",
                    "message": f"Declared report_data source is missing: {source_name}",
                    "path": source_name,
                }
            )
            checked_sources[source_name] = source_metadata
            continue
        actual_sha256 = _sha256_path(path)
        source_metadata.update(
            {
                "exists": True,
                "actual_sha256": actual_sha256,
            }
        )
        if actual_sha256 != expected_sha256:
            issues.append(
                {
                    "code": "SOURCE_HASH_MISMATCH",
                    "severity": "critical",
                    "message": (
                        f"Declared report_data source hash does not match: {source_name}"
                    ),
                    "path": source_name,
                    "expected_sha256": expected_sha256,
                    "actual_sha256": actual_sha256,
                }
            )
        checked_sources[source_name] = source_metadata

    return (
        {
            "status": "fail" if issues else "pass",
            "sources": checked_sources,
            "issue_count": len(issues),
        },
        issues,
    )


def _target_assessment_check(
    base: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lr_candidates_exists = (base / "lr_candidates.json").exists()
    target_metadata = _json_metadata(base, "target_assessment.json")
    if not lr_candidates_exists:
        return (
            {
                "status": "skipped",
                "expected": False,
                "lr_candidates": _json_metadata(base, "lr_candidates.json"),
                "target_assessment": target_metadata,
            },
            [],
        )

    validation = validate_target_assessment_file(base)
    valid = validation.get("valid") is True
    check = {
        "status": "pass" if valid else "fail",
        "expected": True,
        "lr_candidates": _json_metadata(base, "lr_candidates.json"),
        "target_assessment": target_metadata,
        "validation": validation,
    }
    if valid:
        return check, []
    issue_code = (
        "MISSING_TARGET_ASSESSMENT"
        if not target_metadata["exists"]
        else "TARGET_ASSESSMENT_HARNESS_FAILED"
    )
    return (
        check,
        [
            {
                "code": issue_code,
                "severity": "critical",
                "message": "Expected target_assessment.json failed harness validation",
                "path": "target_assessment.json",
                "errors": validation.get("errors", []),
            }
        ],
    )


def _optional_legacy_artifacts(base: Path) -> dict[str, Any]:
    artifacts = {
        name: _json_metadata(base, name) for name in OPTIONAL_LEGACY_ARTIFACTS
    }
    status = (
        "present"
        if any(item["exists"] for item in artifacts.values())
        else "absent"
    )
    return {
        "status": status,
        "artifacts": artifacts,
    }


def _interpretation_check(base: Path) -> dict[str, Any]:
    metadata = _json_metadata(base, "report_interpretations.json")
    if not metadata["exists"]:
        return {"status": "absent", "artifact": metadata}
    if metadata.get("valid_json") is False:
        return {"status": "malformed", "artifact": metadata}
    payload = _read_json(base / "report_interpretations.json")
    summary = payload.get("summary") if isinstance(payload, dict) else None
    return {
        "status": "present",
        "artifact": metadata,
        "summary": summary if isinstance(summary, dict) else {},
    }


def _no_llm_success_check(
    finalizer_result: Mapping[str, Any] | None,
    diagnostics_valid: bool,
) -> dict[str, Any]:
    if finalizer_result is None:
        return {
            "status": "skipped",
            "reason": "finalizer_result is not available",
        }
    finalizer_error = finalizer_result.get("report_finalization_error")
    evidence_truncated = bool(finalizer_result.get("evidence_truncated"))
    passed = (
        finalizer_error is None
        and diagnostics_valid
        and not evidence_truncated
    )
    return {
        "status": "pass" if passed else "fail",
        "report_finalization_error": finalizer_error,
        "diagnostics_valid": diagnostics_valid,
        "evidence_truncated": evidence_truncated,
    }


def deepagents_boundary_contract() -> dict[str, Any]:
    """Return the MVP2 responsibility boundary for DeepAgents integration."""
    return {
        "deepagents": {
            "allowed": list(DEEPAGENTS_ALLOWED_RESPONSIBILITIES),
            "forbidden": list(DEEPAGENTS_FORBIDDEN_RESPONSIBILITIES),
        },
        "deterministic_code": {
            "owns": list(DETERMINISTIC_CODE_OWNS),
        },
    }


def collect_report_harness_diagnostics(data_dir: str) -> dict[str, Any]:
    """Collect deterministic diagnostics for a report workspace."""
    base = Path(data_dir).expanduser().resolve()
    evidence = {name: _json_metadata(base, name) for name in REQUIRED_EVIDENCE}
    artifacts = {
        name: (
            _json_metadata(base, name)
            if name.endswith(".json")
            else _artifact_metadata(base, name)
        )
        for name in REQUIRED_REPORT_ARTIFACTS
    }
    issues = [
        *_missing_required_evidence_issues(evidence),
        *_artifact_issues(base, artifacts),
        *_report_validation_issues(base),
    ]
    source_consistency, source_issues = _source_consistency_check(base)
    target_assessment, target_issues = _target_assessment_check(base)
    issues.extend(source_issues)
    issues.extend(target_issues)
    checks = {
        "artifact_validity": _artifact_validity_check(artifacts, issues),
        "source_consistency": source_consistency,
        "target_assessment": target_assessment,
        "optional_legacy_artifacts": _optional_legacy_artifacts(base),
        "interpretations": _interpretation_check(base),
    }
    return {
        "schema_version": HARNESS_SCHEMA_VERSION,
        "valid": not issues,
        "created_at": _utc_now(),
        "data_dir": str(base),
        "artifacts": artifacts,
        "evidence": evidence,
        "issues": issues,
        "checks": checks,
        "deepagents_boundary": deepagents_boundary_contract(),
    }


def write_report_harness_diagnostics(
    data_dir: str,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write report_harness_diagnostics.json and return the written payload."""
    base = Path(data_dir).expanduser().resolve()
    payload = (
        diagnostics
        if diagnostics is not None
        else collect_report_harness_diagnostics(str(base))
    )
    _write_json(base / HARNESS_DIAGNOSTICS_FILENAME, payload)
    return payload


def _finalizer_exception_result(exc: Exception) -> dict[str, Any]:
    return {
        "report_finalization_error": (
            f"deterministic_report_exception: {type(exc).__name__}: {exc}"
        ),
        "evidence_truncated": False,
    }


def _finalizer_exception_issue(exc: Exception) -> dict[str, Any]:
    return {
        "code": "FINALIZER_EXCEPTION",
        "severity": "critical",
        "message": "Deterministic report finalizer raised before returning a result",
        "exception_type": type(exc).__name__,
        "error": str(exc),
    }


async def run_deterministic_report_harness(
    state: dict[str, Any],
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Run the no-LLM MVP finalizer and persist MVP2 harness diagnostics."""
    base = Path(state["data_dir"]).expanduser().resolve()
    finalizer_state = {
        **state,
        "data_dir": str(base),
    }
    try:
        finalizer_result = await finalize_report_mvp(finalizer_state, config or {})
    except Exception as exc:
        finalizer_result = _finalizer_exception_result(exc)
        diagnostics = collect_report_harness_diagnostics(str(base))
        diagnostics["issues"].append(_finalizer_exception_issue(exc))
        diagnostics["valid"] = False
    else:
        diagnostics = collect_report_harness_diagnostics(str(base))
    diagnostics["finalizer_result"] = finalizer_result
    diagnostics["checks"]["no_llm_success"] = _no_llm_success_check(
        finalizer_result,
        bool(diagnostics["valid"]),
    )
    write_report_harness_diagnostics(str(base), diagnostics)
    return {
        "report_finalization_error": finalizer_result.get(
            "report_finalization_error"
        ),
        "evidence_truncated": bool(finalizer_result.get("evidence_truncated")),
        "report_harness_diagnostics": diagnostics,
        "report_harness_diagnostics_path": str(
            base / HARNESS_DIAGNOSTICS_FILENAME
        ),
    }
