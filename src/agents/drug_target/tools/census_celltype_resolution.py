"""Deterministic Census cell_type resolution helpers."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.tools import tool

_DEFAULT_CENSUS_VERSION = os.getenv("CENSUS_VERSION", "2025-11-08")

_ORGANISM_MAP = {
    "human": "homo_sapiens",
    "homo sapiens": "homo_sapiens",
    "mouse": "mus_musculus",
    "mus musculus": "mus_musculus",
}

_ALIAS_CANONICAL_LABELS = {
    "at2": "pulmonary alveolar type 2 cell",
    "alveolar type 2": "pulmonary alveolar type 2 cell",
    "alveolar type ii": "pulmonary alveolar type 2 cell",
    "type ii": "pulmonary alveolar type 2 cell",
    "type 2 pneumocyte": "pulmonary alveolar type 2 cell",
    "type ii pneumocyte": "pulmonary alveolar type 2 cell",
    "pulmonary alveolar type 2": "pulmonary alveolar type 2 cell",
    "tumor cell": "malignant cell",
    "tumour cell": "malignant cell",
    "immune cell": "leukocyte",
}

_STATE_MODIFIERS = {
    "transitional",
    "cycling",
    "activated",
    "damaged",
    "stressed",
    "proliferating",
    "inflamed",
    "senescent",
    "reactive",
    "injured",
    "apoptotic",
    "differentiating",
    "dedifferentiated",
    "exhausted",
}


def _normalize_label(value: str) -> str:
    lowered = value.strip().lower().replace("-", " ")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _available_by_normalized(
    available_cell_type_counts: dict[str, int],
) -> dict[str, list[tuple[str, int]]]:
    by_normalized: dict[str, list[tuple[str, int]]] = {}
    for label, count in available_cell_type_counts.items():
        by_normalized.setdefault(_normalize_label(label), []).append((label, int(count)))
    return by_normalized


def _best(labels: list[tuple[str, int]]) -> tuple[str, int]:
    return max(labels, key=lambda item: item[1])


def _match_exact(
    normalized_input: str,
    by_normalized: dict[str, list[tuple[str, int]]],
) -> tuple[str, int] | None:
    labels = by_normalized.get(normalized_input)
    if not labels:
        return None
    return _best(labels)


def _match_substring(
    normalized_input: str,
    by_normalized: dict[str, list[tuple[str, int]]],
) -> tuple[str, int] | None:
    partial = [
        candidate
        for normalized_label, labels in by_normalized.items()
        if normalized_input in normalized_label or normalized_label in normalized_input
        for candidate in labels
    ]
    if not partial:
        return None
    return _best(partial)


def _match_alias(
    normalized_input: str,
    by_normalized: dict[str, list[tuple[str, int]]],
) -> tuple[str, int] | None:
    canonical = _ALIAS_CANONICAL_LABELS.get(normalized_input)
    if not canonical:
        return None
    return _match_exact(_normalize_label(canonical), by_normalized)


def _strip_state_modifiers(normalized_input: str) -> tuple[str, list[str]]:
    tokens = normalized_input.split()
    lost = [token for token in tokens if token in _STATE_MODIFIERS]
    stripped = " ".join(token for token in tokens if token not in _STATE_MODIFIERS)
    return stripped, lost


def _resolve_one(
    input_celltype: str,
    by_normalized: dict[str, list[tuple[str, int]]],
) -> dict[str, Any]:
    normalized_input = _normalize_label(input_celltype)
    warnings: list[str] = []

    literal_exact = _match_exact(normalized_input, by_normalized)
    if literal_exact:
        matched, count = literal_exact
        return {
            "input_celltype": input_celltype,
            "matched_celltype": matched,
            "match_mode": "exact",
            "confidence": "high",
            "literal_exact_match": True,
            "literal_substring_match": True,
            "lost_modifiers": [],
            "total_cell_count": count,
            "warnings": warnings,
        }

    literal_substring = _match_substring(normalized_input, by_normalized)
    if literal_substring:
        matched, count = literal_substring
        return {
            "input_celltype": input_celltype,
            "matched_celltype": matched,
            "match_mode": "substring",
            "confidence": "medium",
            "literal_exact_match": False,
            "literal_substring_match": True,
            "lost_modifiers": [],
            "total_cell_count": count,
            "warnings": warnings,
        }

    alias = _match_alias(normalized_input, by_normalized)
    if alias:
        matched, count = alias
        return {
            "input_celltype": input_celltype,
            "matched_celltype": matched,
            "match_mode": "alias",
            "confidence": "high",
            "literal_exact_match": False,
            "literal_substring_match": False,
            "lost_modifiers": [],
            "total_cell_count": count,
            "warnings": warnings,
        }

    stripped, lost_modifiers = _strip_state_modifiers(normalized_input)
    if lost_modifiers and stripped:
        stripped_exact = _match_exact(stripped, by_normalized)
        stripped_alias = _match_alias(stripped, by_normalized)
        stripped_substring = _match_substring(stripped, by_normalized)
        stripped_match = stripped_exact or stripped_alias or stripped_substring
        if stripped_match:
            matched, count = stripped_match
            base_mode = (
                "exact"
                if stripped_exact
                else "alias"
                if stripped_alias
                else "substring"
            )
            warnings.append(
                "State modifier(s) "
                f"{', '.join(lost_modifiers)} were stripped from interest cell type "
                f"'{input_celltype}' before matching '{matched}'."
            )
            return {
                "input_celltype": input_celltype,
                "matched_celltype": matched,
                "match_mode": f"state_stripped_{base_mode}",
                "confidence": "medium",
                "literal_exact_match": False,
                "literal_substring_match": False,
                "lost_modifiers": lost_modifiers,
                "total_cell_count": count,
                "warnings": warnings,
            }

    warnings.append(
        f"No Census cell_type label matched interest cell type '{input_celltype}'."
    )
    return {
        "input_celltype": input_celltype,
        "matched_celltype": "",
        "match_mode": "unresolved",
        "confidence": "none",
        "literal_exact_match": False,
        "literal_substring_match": False,
        "lost_modifiers": [],
        "total_cell_count": 0,
        "warnings": warnings,
    }


def resolve_celltype_matches(
    interest_celltypes: list[str],
    available_cell_type_counts: dict[str, int],
    *,
    disease: str,
    organism: str,
    disease_resolved: str,
    disease_resolution_mode: str,
) -> dict[str, Any]:
    """Resolve interest cell types to available Census cell_type labels."""
    by_normalized = _available_by_normalized(available_cell_type_counts)
    matches = [
        _resolve_one(celltype, by_normalized)
        for celltype in interest_celltypes
        if isinstance(celltype, str)
    ]
    primary = next((match for match in matches if match["matched_celltype"]), None)
    warnings = [warning for match in matches for warning in match.get("warnings", [])]

    return {
        "organism": organism,
        "disease_input": disease,
        "disease_resolved": disease_resolved,
        "disease_resolution_mode": disease_resolution_mode,
        "interest_celltypes": interest_celltypes,
        "available_cell_type_count": len(available_cell_type_counts),
        "primary_input_celltype": primary["input_celltype"] if primary else "",
        "primary_resolved_celltype": primary["matched_celltype"] if primary else "",
        "primary_match_mode": primary["match_mode"] if primary else "unresolved",
        "matches": matches,
        "warnings": warnings,
        "errors": [],
        "executed": True,
        "census_version": _DEFAULT_CENSUS_VERSION,
    }


def _resolve_disease_for_census(disease: str, organism: str) -> tuple[str, str]:
    try:
        from src.agents.drug_target.tools.census_batch_core import _resolve_disease_name

        resolved, mode = _resolve_disease_name(disease, organism)
    except Exception:
        return disease, "input"
    if not resolved:
        return disease, mode
    return resolved, mode


def _escape_census_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _query_available_cell_type_counts(
    *,
    disease_resolved: str,
    organism: str,
) -> tuple[dict[str, int], list[str]]:
    errors: list[str] = []
    try:
        import cellxgene_census
    except Exception as exc:
        return {}, [f"cellxgene_census unavailable: {exc}"]

    try:
        disease_safe = _escape_census_literal(disease_resolved)
        with cellxgene_census.open_soma(census_version=_DEFAULT_CENSUS_VERSION) as census:
            obs = cellxgene_census.get_obs(
                census,
                organism,
                value_filter=(
                    "is_primary_data == True "
                    f"and disease == '{disease_safe}'"
                ),
                column_names=["cell_type"],
            )
        counts = obs["cell_type"].value_counts()
        return {str(label): int(count) for label, count in counts.items()}, errors
    except Exception as exc:
        errors.append(f"Census cell_type query failed: {exc}")
        return {}, errors


@tool
def resolve_census_celltypes(
    interest_celltypes: list[str],
    disease: str,
    organism: str = "homo_sapiens",
) -> str:
    """Resolve interest cell types to disease-scoped CELLxGENE Census labels."""
    organism = _ORGANISM_MAP.get(organism.lower().strip(), organism)
    disease_resolved, disease_resolution_mode = _resolve_disease_for_census(
        disease, organism
    )
    counts, errors = _query_available_cell_type_counts(
        disease_resolved=disease_resolved,
        organism=organism,
    )
    result = resolve_celltype_matches(
        interest_celltypes,
        counts,
        disease=disease,
        organism=organism,
        disease_resolved=disease_resolved,
        disease_resolution_mode=disease_resolution_mode,
    )
    result["executed"] = not errors
    result["errors"] = errors
    return json.dumps(result, indent=2)
