"""Deterministic Census cell_type resolution helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
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


def _available_options(
    available_cell_type_counts: dict[str, int],
) -> list[dict[str, Any]]:
    return [
        {"label": label, "total_cell_count": int(count)}
        for label, count in sorted(
            available_cell_type_counts.items(),
            key=lambda item: (-int(item[1]), item[0].lower()),
        )
    ]


def _options_sha256(options: list[dict[str, Any]]) -> str:
    payload = json.dumps(options, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


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
    if not normalized_input:
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
            "candidate_labels_considered": [],
            "semantic_proxy_rationale": "",
            "total_cell_count": 0,
            "warnings": warnings,
        }

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
            "candidate_labels_considered": [],
            "semantic_proxy_rationale": "",
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
                "candidate_labels_considered": [],
                "semantic_proxy_rationale": "",
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
            "candidate_labels_considered": [],
            "semantic_proxy_rationale": "",
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
            "candidate_labels_considered": [],
            "semantic_proxy_rationale": "",
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
        "candidate_labels_considered": [],
        "semantic_proxy_rationale": "",
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
    preview_limit: int = 25,
) -> dict[str, Any]:
    """Resolve interest cell types to available Census cell_type labels."""
    by_normalized = _available_by_normalized(available_cell_type_counts)
    options = _available_options(available_cell_type_counts)
    preview_limit_int = int(preview_limit)
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
        "available_celltype_preview": options[: max(0, preview_limit_int)],
        "available_celltype_preview_limit": preview_limit_int,
        "available_celltype_options_path": "",
        "available_celltype_options_sha256": _options_sha256(options),
        "primary_input_celltype": primary["input_celltype"] if primary else "",
        "primary_resolved_celltype": primary["matched_celltype"] if primary else "",
        "primary_match_mode": primary["match_mode"] if primary else "unresolved",
        "matches": matches,
        "warnings": warnings,
        "errors": [],
        "executed": True,
        "census_version": _DEFAULT_CENSUS_VERSION,
    }


def _evidence_dir(data_dir: str) -> Path:
    return Path(data_dir).expanduser().resolve() / "evidence"


def _write_celltype_options_artifact(
    *,
    data_dir: str,
    organism: str,
    disease_input: str,
    disease_resolved: str,
    disease_resolution_mode: str,
    available_cell_type_counts: dict[str, int],
) -> tuple[str, str]:
    options = _available_options(available_cell_type_counts)
    payload = {
        "organism": organism,
        "disease_input": disease_input,
        "disease_resolved": disease_resolved,
        "disease_resolution_mode": disease_resolution_mode,
        "available_celltype_count": len(options),
        "available_celltype_options_sha256": _options_sha256(options),
        "available_celltype_options": options,
    }
    evidence_dir = _evidence_dir(data_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "census_celltype_options.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return "evidence/census_celltype_options.json", payload[
        "available_celltype_options_sha256"
    ]


def _load_celltype_options_artifact(data_dir: str) -> dict[str, Any]:
    path = _evidence_dir(data_dir) / "census_celltype_options.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_celltype_options_artifact(
    artifact: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, str]:
    options = artifact.get("available_celltype_options")
    if not isinstance(options, list):
        return (
            [],
            "",
            "Census cell_type options artifact is invalid: "
            "available_celltype_options must be a list.",
        )

    recomputed_sha256 = _options_sha256(options)
    stored_sha256 = str(artifact.get("available_celltype_options_sha256", "") or "")
    if not stored_sha256:
        return (
            options,
            recomputed_sha256,
            "Census cell_type options artifact hash missing: "
            "available_celltype_options_sha256 is required.",
        )
    if stored_sha256 != recomputed_sha256:
        return (
            options,
            recomputed_sha256,
            "Census cell_type options artifact hash mismatch: "
            "stored available_celltype_options_sha256 does not match "
            "available_celltype_options.",
        )
    return options, recomputed_sha256, ""


def _validate_celltype_options_artifact_for_result(
    artifact: dict[str, Any],
    resolution_result: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    options, recomputed_sha256, artifact_error = _validate_celltype_options_artifact(
        artifact
    )
    if artifact_error:
        return options, artifact_error

    resolver_sha256 = str(
        resolution_result.get("available_celltype_options_sha256", "") or ""
    )
    if not resolver_sha256:
        return (
            options,
            "Census cell_type options artifact hash does not match resolver result: "
            "resolver result is missing available_celltype_options_sha256.",
        )
    if recomputed_sha256 != resolver_sha256:
        return (
            options,
            "Census cell_type options artifact hash does not match resolver result: "
            "artifact available_celltype_options_sha256 differs from resolver "
            "result available_celltype_options_sha256.",
        )
    return options, ""


def _resolve_disease_for_census(
    disease: str,
    organism: str,
) -> tuple[str, str, list[str]]:
    try:
        from src.agents.drug_target.tools.census_batch_core import _resolve_disease_name

        resolved, mode = _resolve_disease_name(disease, organism)
    except Exception as exc:
        return (
            disease,
            "input",
            [f"Census disease resolution failed for {disease!r}: {exc}"],
        )
    if not resolved:
        return disease, mode, []
    return resolved, mode, []


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
    data_dir: str = "",
    preview_limit: int = 25,
) -> str:
    """Resolve interest cell types to disease-scoped CELLxGENE Census labels."""
    organism = _ORGANISM_MAP.get(organism.lower().strip(), organism)
    disease_resolved, disease_resolution_mode, disease_errors = (
        _resolve_disease_for_census(disease, organism)
    )
    counts, query_errors = _query_available_cell_type_counts(
        disease_resolved=disease_resolved,
        organism=organism,
    )
    errors = [*disease_errors, *query_errors]
    result = resolve_celltype_matches(
        interest_celltypes,
        counts,
        disease=disease,
        organism=organism,
        disease_resolved=disease_resolved,
        disease_resolution_mode=disease_resolution_mode,
        preview_limit=preview_limit,
    )
    if data_dir and counts:
        try:
            options_path, options_sha256 = _write_celltype_options_artifact(
                data_dir=data_dir,
                organism=organism,
                disease_input=disease,
                disease_resolved=disease_resolved,
                disease_resolution_mode=disease_resolution_mode,
                available_cell_type_counts=counts,
            )
            result["available_celltype_options_path"] = options_path
            result["available_celltype_options_sha256"] = options_sha256
        except Exception as exc:
            errors.append(f"Census cell_type options artifact write failed: {exc}")
    result["executed"] = not errors
    result["errors"] = errors
    return json.dumps(result, indent=2)


def _score_option(query: str, label: str) -> int:
    normalized_query = _normalize_label(query)
    normalized_label = _normalize_label(label)
    if not normalized_query:
        return 0
    query_tokens = set(normalized_query.split())
    label_tokens = set(normalized_label.split())
    score = len(query_tokens.intersection(label_tokens))
    if normalized_query in normalized_label and normalized_query not in label_tokens:
        score += 1
    return score


@tool
def search_census_celltype_options(
    data_dir: str,
    query: str = "",
    top_k: int = 25,
) -> str:
    """Search saved disease-scoped Census cell_type options without returning the full set."""
    try:
        payload = _load_celltype_options_artifact(data_dir)
    except Exception as exc:
        return json.dumps(
            {
                "executed": False,
                "query": query,
                "matches": [],
                "errors": [f"Census cell_type options artifact read failed: {exc}"],
            },
            indent=2,
        )

    options, _options_hash, artifact_error = _validate_celltype_options_artifact(
        payload
    )
    if artifact_error:
        return json.dumps(
            {
                "executed": False,
                "query": query,
                "matches": [],
                "errors": [artifact_error],
            },
            indent=2,
        )

    ranked = [
        {
            "label": str(option.get("label", "")),
            "total_cell_count": int(option.get("total_cell_count", 0) or 0),
            "score": _score_option(query, str(option.get("label", ""))),
        }
        for option in options
        if isinstance(option, dict)
    ]
    if query:
        ranked = [option for option in ranked if option["score"] > 0]
    ranked.sort(
        key=lambda option: (
            -option["score"],
            -option["total_cell_count"],
            option["label"].lower(),
        )
    )
    return json.dumps(
        {
            "executed": True,
            "query": query,
            "top_k": int(top_k),
            "matches": ranked[: max(0, int(top_k))],
            "errors": [],
        },
        indent=2,
    )


def _available_label_map_from_options(
    available_celltype_options: list[dict[str, Any]],
) -> dict[str, tuple[str, int]]:
    labels: dict[str, tuple[str, int]] = {}
    for option in available_celltype_options:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label", ""))
        if not label:
            continue
        labels[_normalize_label(label)] = (
            label,
            int(option.get("total_cell_count", 0) or 0),
        )
    return labels


def _clone_resolution_result(result: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(result))


def apply_semantic_celltype_proxy_to_result(
    resolution_result: dict[str, Any],
    *,
    available_celltype_options: list[dict[str, Any]],
    input_celltype: str,
    matched_celltype: str,
    rationale: str,
    confidence: str = "medium",
    lost_modifiers: list[str] | None = None,
    candidate_labels_considered: list[str] | None = None,
) -> dict[str, Any]:
    """Apply an agent-selected Census proxy after validating full-option membership."""
    result = _clone_resolution_result(resolution_result)
    result.setdefault("errors", [])
    result.setdefault("warnings", [])

    available = _available_label_map_from_options(available_celltype_options)
    normalized_match = _normalize_label(matched_celltype)
    if normalized_match not in available:
        result["errors"].append(
            f"Semantic proxy label {matched_celltype!r} is not present in "
            "available Census cell_type labels."
        )
        return result

    target_index = None
    for index, match in enumerate(result.get("matches", [])):
        if match.get("input_celltype") == input_celltype:
            target_index = index
            break
    if target_index is None:
        result["errors"].append(
            f"Input cell type {input_celltype!r} was not found in resolver matches."
        )
        return result

    canonical_label, count = available[normalized_match]
    lost = list(lost_modifiers or [])
    considered = list(candidate_labels_considered or [canonical_label])
    warning = (
        f"Interest cell type {input_celltype!r} was resolved by semantic proxy "
        f"to Census label {canonical_label!r}. Do not interpret this as "
        "state-specific Census validation."
    )
    result["matches"][target_index].update(
        {
            "matched_celltype": canonical_label,
            "match_mode": "semantic_proxy",
            "confidence": confidence,
            "literal_exact_match": False,
            "literal_substring_match": False,
            "lost_modifiers": lost,
            "candidate_labels_considered": considered,
            "semantic_proxy_rationale": rationale,
            "total_cell_count": count,
            "warnings": [
                warning,
                *result["matches"][target_index].get("warnings", []),
            ],
        }
    )

    primary = next(
        (match for match in result.get("matches", []) if match.get("matched_celltype")),
        None,
    )
    result["primary_input_celltype"] = (
        primary.get("input_celltype", "") if primary else ""
    )
    result["primary_resolved_celltype"] = (
        primary.get("matched_celltype", "") if primary else ""
    )
    result["primary_match_mode"] = (
        primary.get("match_mode", "unresolved") if primary else "unresolved"
    )
    result["warnings"] = [
        warning
        for match in result.get("matches", [])
        for warning in match.get("warnings", [])
    ]
    return result


@tool
def apply_semantic_celltype_proxy(
    resolution_result: dict[str, Any],
    data_dir: str,
    input_celltype: str,
    matched_celltype: str,
    rationale: str,
    confidence: str = "medium",
    lost_modifiers: list[str] | None = None,
    candidate_labels_considered: list[str] | None = None,
) -> str:
    """Validate and record an agent-selected semantic Census cell_type proxy."""
    try:
        artifact = _load_celltype_options_artifact(data_dir)
    except Exception as exc:
        result = _clone_resolution_result(resolution_result)
        result.setdefault("errors", [])
        result["errors"].append(f"Census cell_type options artifact read failed: {exc}")
        return json.dumps(result, indent=2)

    options, artifact_error = _validate_celltype_options_artifact_for_result(
        artifact,
        resolution_result,
    )
    if artifact_error:
        result = _clone_resolution_result(resolution_result)
        result.setdefault("errors", [])
        result["errors"].append(artifact_error)
        return json.dumps(result, indent=2)

    result = apply_semantic_celltype_proxy_to_result(
        resolution_result,
        available_celltype_options=options,
        input_celltype=input_celltype,
        matched_celltype=matched_celltype,
        rationale=rationale,
        confidence=confidence,
        lost_modifiers=lost_modifiers,
        candidate_labels_considered=candidate_labels_considered,
    )
    return json.dumps(result, indent=2)
