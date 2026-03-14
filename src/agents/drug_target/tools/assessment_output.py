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


def _load_input_pairs(base: Path) -> list[tuple[str, str]]:
    lr_path = base / "lr_candidates.json"
    if not lr_path.exists():
        return []
    try:
        lr_data = json.loads(lr_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    pairs = (
        lr_data.get("pairs")
        or lr_data.get("lr_pairs")
        or lr_data.get("candidates")
        or lr_data.get("candidate_pairs")
        or []
    )
    loaded: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        ligand = str(pair.get("ligand") or pair.get("source") or "").strip().upper()
        receptor = str(pair.get("receptor") or pair.get("target") or "").strip().upper()
        if not ligand or not receptor:
            continue
        item = (ligand, receptor)
        if item in seen:
            continue
        seen.add(item)
        loaded.append(item)
    return loaded


def _extract_deep_dive_gene(entry: dict[str, Any]) -> str:
    for key in ("gene", "gene_symbol", "target_gene"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value.upper()
    return ""


def _extract_deep_dive_track(entry: dict[str, Any]) -> str:
    value = str(entry.get("track") or entry.get("candidate_type") or "").strip().lower()
    if value in {"featured", "novel"}:
        return value
    return ""


def _validate_contract(
    payload: dict[str, Any],
    errors: list[str],
    *,
    base: Path | None = None,
) -> bool:
    initial_count = len(errors)
    if not isinstance(payload.get("project_meta"), dict):
        errors.append("project_meta must be an object")
    if not isinstance(payload.get("druggability_matrix"), list):
        errors.append("druggability_matrix must be an array")
    if not isinstance(payload.get("featured_candidates_deep_dive"), list):
        errors.append("featured_candidates_deep_dive must be an array")

    matrix = payload.get("druggability_matrix", [])
    for idx, row in enumerate(matrix):
        for key in ("ligand", "receptor", "is_featured", "is_novel", "open_targets_score"):
            if key not in row:
                errors.append(f"druggability_matrix[{idx}] missing required key: {key}")

    if base is not None:
        input_pairs = _load_input_pairs(base)
        if not input_pairs:
            errors.append(f"lr_candidates.json missing or unreadable at {base / 'lr_candidates.json'}")
        else:
            project_meta = payload.get("project_meta", {})
            total_input_pairs = project_meta.get("total_input_pairs")
            if total_input_pairs != len(input_pairs):
                errors.append(
                    "project_meta.total_input_pairs must equal the number of input L-R pairs "
                    f"({len(input_pairs)}); got {total_input_pairs!r}"
                )

            input_pair_keys = {f"{ligand}^{receptor}" for ligand, receptor in input_pairs}
            matrix_pair_keys = {
                f"{str(row.get('ligand', '')).strip().upper()}^{str(row.get('receptor', '')).strip().upper()}"
                for row in matrix
                if str(row.get("ligand", "")).strip() and str(row.get("receptor", "")).strip()
            }
            missing_pairs = sorted(input_pair_keys - matrix_pair_keys)
            extra_pairs = sorted(matrix_pair_keys - input_pair_keys)
            if missing_pairs or extra_pairs:
                errors.append(
                    "druggability_matrix pair-set must match lr_candidates.json exactly; "
                    f"missing={missing_pairs}, extra={extra_pairs}"
                )

            featured_genes = {
                gene
                for row in matrix
                if row.get("is_featured")
                for gene in (
                    str(row.get("ligand", "")).strip().upper(),
                    str(row.get("receptor", "")).strip().upper(),
                )
                if gene
            }
            novel_genes = {
                gene
                for row in matrix
                if row.get("is_novel")
                for gene in (
                    str(row.get("ligand", "")).strip().upper(),
                    str(row.get("receptor", "")).strip().upper(),
                )
                if gene
            }
            all_matrix_genes = {
                gene
                for row in matrix
                for gene in (
                    str(row.get("ligand", "")).strip().upper(),
                    str(row.get("receptor", "")).strip().upper(),
                )
                if gene
            }
            for idx, entry in enumerate(payload.get("featured_candidates_deep_dive", [])):
                if not isinstance(entry, dict):
                    errors.append(f"featured_candidates_deep_dive[{idx}] must be an object")
                    continue
                gene = _extract_deep_dive_gene(entry)
                track = _extract_deep_dive_track(entry)
                if not gene:
                    errors.append(
                        f"featured_candidates_deep_dive[{idx}] must include one of gene/gene_symbol/target_gene"
                    )
                    continue
                if gene not in all_matrix_genes:
                    errors.append(
                        f"featured_candidates_deep_dive[{idx}] gene {gene} does not appear in druggability_matrix"
                    )
                    continue
                if track == "featured" and gene not in featured_genes:
                    errors.append(
                        f"featured_candidates_deep_dive[{idx}] gene {gene} is not part of a featured matrix row"
                    )
                if track == "novel" and gene not in novel_genes:
                    errors.append(
                        f"featured_candidates_deep_dive[{idx}] gene {gene} is not part of a novel matrix row"
                    )

    return len(errors) == initial_count


def validate_target_assessment_file(data_dir: str | Path) -> dict[str, Any]:
    """Validate the saved target_assessment.json against the workspace input pairs."""
    base = _resolve_data_dir(str(data_dir))
    out_path = base / "target_assessment.json"
    if not out_path.exists():
        return {
            "valid": False,
            "path": str(out_path),
            "errors": [f"target_assessment.json not found at {out_path}"],
        }
    try:
        payload = json.loads(out_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "valid": False,
            "path": str(out_path),
            "errors": [f"Failed to parse target_assessment.json: {exc}"],
        }

    errors: list[str] = []
    valid = _validate_contract(payload, errors, base=base)
    return {
        "valid": valid,
        "path": str(out_path),
        "errors": errors,
        "matrix_pair_count": len(payload.get("druggability_matrix", [])),
    }


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

    schema_valid = _validate_contract(payload, schema_errors, base=base)
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
