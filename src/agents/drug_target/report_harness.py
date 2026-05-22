"""No-LLM harness diagnostics for deterministic drug-target reports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

from src.agents.drug_target.deterministic_report import finalize_report_mvp
from src.agents.drug_target.evidence_filenames import EvidenceFiles


HARNESS_SCHEMA_VERSION = "drug_target.report_harness_diagnostics.v1"
HARNESS_DIAGNOSTICS_FILENAME = "report_harness_diagnostics.json"
REQUIRED_REPORT_ARTIFACTS = (
    "report_data.json",
    "drug.md",
    "drug_report.html",
    "report_validation.json",
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
        if path.exists() and "EXPAND" in path.read_text(encoding="utf-8"):
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
    return {
        "schema_version": HARNESS_SCHEMA_VERSION,
        "valid": not issues,
        "created_at": _utc_now(),
        "data_dir": str(base),
        "artifacts": artifacts,
        "evidence": evidence,
        "issues": issues,
        "deepagents_boundary": deepagents_boundary_contract(),
    }


def write_report_harness_diagnostics(
    data_dir: str,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write report_harness_diagnostics.json and return the written payload."""
    base = Path(data_dir).expanduser().resolve()
    payload = diagnostics or collect_report_harness_diagnostics(str(base))
    _write_json(base / HARNESS_DIAGNOSTICS_FILENAME, payload)
    return payload


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
    finalizer_result = await finalize_report_mvp(finalizer_state, config or {})
    diagnostics = collect_report_harness_diagnostics(str(base))
    diagnostics["finalizer_result"] = finalizer_result
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
