"""Output contract helpers for target_assessment.json generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir
from src.agents.drug_target.tools.stage_logic import rank_featured_candidates


def _parse_json_param(raw: str, field_name: str, errors: list[str]) -> Any:
    try:
        return json.loads(raw)
    except Exception as exc:
        errors.append(f"Invalid JSON for {field_name}: {exc}")
        return None


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[4] / "docs" / "drugtarget" / "output_schema.json"


def _validate_contract(payload: dict[str, Any], errors: list[str]) -> bool:
    if not isinstance(payload.get("project_meta"), dict):
        errors.append("project_meta must be an object")
    if not isinstance(payload.get("druggability_matrix"), list):
        errors.append("druggability_matrix must be an array")
    if not isinstance(payload.get("featured_candidates_deep_dive"), list):
        errors.append("featured_candidates_deep_dive must be an array")

    matrix = payload.get("druggability_matrix", [])
    for idx, row in enumerate(matrix):
        for key in ("ligand", "receptor", "is_featured", "open_targets_score"):
            if key not in row:
                errors.append(f"druggability_matrix[{idx}] missing required key: {key}")

    return not errors


@tool
def save_target_assessment(
    data_dir: str,
    project_meta: str,
    druggability_matrix: str,
    featured_candidates_deep_dive: str,
) -> str:
    """Save target_assessment.json following docs/drugtarget output contract.

    Args:
        data_dir: Output directory
        project_meta: JSON string for project metadata object
        druggability_matrix: JSON string for stage 1/2 matrix rows
        featured_candidates_deep_dive: JSON string for stage 3/4 rows
    """
    errors: list[str] = []
    base = _resolve_data_dir(data_dir)

    project_meta_obj = _parse_json_param(project_meta, "project_meta", errors)
    matrix_obj = _parse_json_param(druggability_matrix, "druggability_matrix", errors)
    deep_dive_obj = _parse_json_param(
        featured_candidates_deep_dive,
        "featured_candidates_deep_dive",
        errors,
    )

    if errors:
        return json.dumps(
            {
                "saved": False,
                "path": str(base / "target_assessment.json"),
                "schema_valid": False,
                "errors": errors,
            },
            indent=2,
        )

    ranked_matrix = rank_featured_candidates(matrix_obj)
    payload = {
        "project_meta": project_meta_obj,
        "druggability_matrix": ranked_matrix,
        "featured_candidates_deep_dive": deep_dive_obj,
    }

    # Load schema file for traceability (best-effort, validation is lightweight here).
    schema_file = _schema_path()
    schema_loaded = schema_file.exists()
    schema_errors: list[str] = []
    if schema_loaded:
        try:
            _ = json.loads(schema_file.read_text(encoding="utf-8"))
        except Exception as exc:
            schema_errors.append(f"Failed to parse output schema: {exc}")

    schema_valid = _validate_contract(payload, schema_errors)
    out_path = base / "target_assessment.json"

    if schema_valid:
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return json.dumps(
        {
            "saved": schema_valid,
            "path": str(out_path),
            "schema_path": str(schema_file),
            "schema_loaded": schema_loaded,
            "schema_valid": schema_valid,
            "errors": schema_errors,
        },
        indent=2,
    )

