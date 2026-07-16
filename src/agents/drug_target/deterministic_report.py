"""No-LLM deterministic report path for drug-target finalization."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment
from langchain_core.runnables import RunnableConfig

from src.agents.drug_target.part4_candidate_selector import (
    PART4_CANDIDATE_SELECTION_FILENAME,
    generate_part4_candidate_selection,
    part4_candidate_selector_enabled,
    part4_candidate_selector_provider_from_config,
)
from src.agents.drug_target.hybrid_report_sections import REPORT_SECTIONS_FILENAME
from src.agents.drug_target.therapeutic_synthesis import (
    PART4_SYNTHESIS_FILENAME,
    build_part4_therapeutic_synthesis,
    render_part4_therapeutic_synthesis_markdown,
)
from src.agents.drug_target.tools.scoring_metadata import NOVELTY_OPPORTUNITY_LEGEND


_SCORE_FIELDS = (
    "existing_drug_evidence",
    "clinical_trial_activity",
    "safety_profile",
    "safety_evidence_level",
    "safety_liability_count",
    "safety_liability_sources",
    "validated_total",
    "gwas_support",
    "gwas_evidence_type",
    "gwas_min_pvalue",
    "gwas_trait_match_level",
    "gwas_direct_hit_count",
    "gwas_proximity_hit_count",
    "tractability",
    "tractability_basis",
    "tractability_modalities",
    "tractability_evidence_label",
    "biological_plausibility_base",
    "stage1_biological_support_bonus",
    "biological_basis",
    "biological_evidence_types",
    "biological_evidence_count",
    "biological_max_ot_score",
    "vep_high_impact_count",
    "stage1_support_pair_count",
    "stage1_support_pairs",
    "stage1_gate_status",
    "stage1_total_pair_count",
    "stage1_passed_pair_count",
    "stage1_failed_pair_count",
    "stage1_best_pair",
    "stage1_best_string_combined",
    "stage1_best_coexpr_pvalue",
    "stage1_best_gene_a_pvalue",
    "stage1_best_gene_b_pvalue",
    "stage1_source",
    "biological_plausibility",
    "novelty_opportunity",
    "novelty_basis",
    "novelty_association_count",
    "novelty_target_drug_count",
    "novelty_bucket",
    "novelty_source",
    "exploratory_total",
    "combined_total",
    "gwas_rank_points",
    "tractability_rank_points",
    "biological_plausibility_rank_points",
    "novelty_opportunity_rank_points",
    "exploratory_rank_total",
    "combined_rank_score",
)
_GWAS_AUDIT_FIELD_DEFAULTS = {
    "gwas_evidence_type": "none",
    "gwas_min_pvalue": None,
    "gwas_trait_match_level": "none",
    "gwas_direct_hit_count": 0,
    "gwas_proximity_hit_count": 0,
}
_TRACTABILITY_AUDIT_FIELD_DEFAULTS = {
    "tractability_basis": "unknown",
    "tractability_modalities": "",
    "tractability_evidence_label": "none",
}
_SAFETY_AUDIT_FIELD_DEFAULTS = {
    "safety_evidence_level": "no_known_liability",
    "safety_liability_count": 0,
    "safety_liability_sources": "",
}
_BIOLOGICAL_AUDIT_FIELD_DEFAULTS = {
    "biological_basis": "none",
    "biological_evidence_types": "",
    "biological_evidence_count": 0,
    "biological_max_ot_score": None,
    "vep_high_impact_count": 0,
    "stage1_support_pair_count": 0,
    "stage1_support_pairs": "",
}
_STAGE1_AUDIT_FIELD_DEFAULTS = {
    "stage1_gate_status": "not_evaluated",
    "stage1_total_pair_count": 0,
    "stage1_passed_pair_count": 0,
    "stage1_failed_pair_count": 0,
    "stage1_best_pair": "",
    "stage1_best_string_combined": None,
    "stage1_best_coexpr_pvalue": None,
    "stage1_best_gene_a_pvalue": None,
    "stage1_best_gene_b_pvalue": None,
    "stage1_source": "none",
}
_NOVELTY_AUDIT_FIELD_DEFAULTS = {
    "novelty_basis": "st_only_or_brand_new_target",
    "novelty_association_count": 0,
    "novelty_target_drug_count": 0,
    "novelty_bucket": "0-9 associations",
    "novelty_source": "list_length",
}
_MARKDOWN_TEMPLATE_SUBPATH = (
    Path("skills")
    / "drug-target-reporting"
    / "templates"
    / "drug_report.md.j2"
)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PACKAGE_MARKDOWN_TEMPLATE = (
    Path(__file__).resolve().parent / "templates" / "drug_report.md.j2"
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return _load_json(path)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required_evidence_paths(base: Path) -> dict[str, Path]:
    return {
        "assessment_results": base / "evidence" / "assessment_results.json",
        "hypothesis_report": base / "evidence" / "hypothesis_report.json",
    }


def _missing_required_evidence(
    base: Path,
    *,
    require_hypothesis: bool = True,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for name, path in _required_evidence_paths(base).items():
        if name == "hypothesis_report" and not require_hypothesis:
            continue
        if not path.exists():
            issues.append(
                {
                    "code": "MISSING_REQUIRED_EVIDENCE",
                    "severity": "critical",
                    "message": (
                        "Required evidence file is missing: "
                        f"{path.relative_to(base)}"
                    ),
                    "path": str(path),
                    "evidence_key": name,
                }
            )
    return issues


def _invalid_report_data(
    base: Path,
    disease: str,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "drug_target.report_data.v1",
        "valid": False,
        "created_at": _utc_now(),
        "data_dir": str(base),
        "disease": disease,
        "issues": issues,
        "sections": {},
        "candidates": [],
        "hypotheses": [],
        "sources": {},
    }


def _invalid_required_json_issue(
    base: Path,
    evidence_key: str,
    path: Path,
    error: Exception,
) -> dict[str, Any]:
    return {
        "code": "INVALID_REQUIRED_EVIDENCE_JSON",
        "severity": "critical",
        "message": (
            "Required evidence file is not valid JSON: "
            f"{path.relative_to(base)}"
        ),
        "path": str(path.relative_to(base)),
        "evidence_key": evidence_key,
        "error": str(error),
    }


def _normalize_gene(value: object) -> str:
    return str(value or "").strip().upper()


def _assessment_rows(
    assessment: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = assessment.get("rubric_assessment")
    if not isinstance(rows, list):
        return [], [
            {
                "code": "INVALID_ASSESSMENT_SHAPE",
                "severity": "critical",
                "message": "assessment_results.json must include rubric_assessment as a list",
                "path": "evidence/assessment_results.json",
            }
        ]
    issues: list[dict[str, Any]] = []
    valid_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if isinstance(row, dict):
            valid_rows.append(row)
            continue
        issues.append(
            {
                "code": "INVALID_ASSESSMENT_ROW",
                "severity": "critical",
                "message": "rubric_assessment rows must be JSON objects",
                "path": "evidence/assessment_results.json",
                "row_index": index,
            }
        )
    return valid_rows, issues


def _stage3_genes(assessment: dict[str, Any], rows: list[dict[str, Any]]) -> set[str]:
    stage3_candidates = assessment.get("stage3_candidates")
    genes: set[str] = set()
    if isinstance(stage3_candidates, list):
        for item in stage3_candidates:
            if isinstance(item, dict):
                gene = _normalize_gene(item.get("gene"))
                if gene:
                    genes.add(gene)
    if genes:
        return genes

    return {
        _normalize_gene(row.get("gene"))
        for row in rows
        if row.get("stage3_candidate")
    }


def _dedupe_strings(values: Sequence[object | None]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _safe_text(value: object, default: str = "not available") -> str:
    text = "" if value is None else str(value).strip()
    return text if text else default


def _markdown_template_path() -> Path:
    explicit_path = os.environ.get("DRUG_TARGET_REPORT_TEMPLATE_PATH")
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if path.exists():
            return path
        raise FileNotFoundError(f"Missing markdown template: {path}")

    explicit_dir = os.environ.get("DRUG_TARGET_REPORT_TEMPLATE_DIR")
    if explicit_dir:
        path = Path(explicit_dir).expanduser().resolve() / "drug_report.md.j2"
        if path.exists():
            return path
        raise FileNotFoundError(f"Missing markdown template: {path}")

    for candidate in (
        _PROJECT_ROOT / _MARKDOWN_TEMPLATE_SUBPATH,
        _PACKAGE_MARKDOWN_TEMPLATE,
    ):
        if candidate.exists():
            return candidate

    for parent in Path(__file__).resolve().parents:
        candidate = parent / _MARKDOWN_TEMPLATE_SUBPATH
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Missing markdown template: {_MARKDOWN_TEMPLATE_SUBPATH}")


def _load_optional_dict(path: Path) -> dict[str, Any]:
    payload = _load_optional_json(path, {})
    return payload if isinstance(payload, dict) else {}


def _load_stage1_filter_results(base: Path) -> list[dict[str, Any]]:
    json_path = base / "evidence" / "stage1_filter_results.json"
    if json_path.exists():
        payload = _load_optional_json(json_path, [])
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

    csv_path = base / "evidence" / "stage1_filter_results.csv"
    if csv_path.exists():
        import csv

        with csv_path.open(encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    return []


def _is_true(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_pvalue(value: object) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "N/A"
    return f"{numeric:.2e}" if numeric < 0.001 else f"{numeric:.4f}"


def _format_rr(value: object) -> str:
    numeric = _float_or_none(value)
    if numeric is None or not (numeric < float("inf") and numeric > float("-inf")):
        return "N/A"
    return f"{numeric:.2f}"


def _format_stage1_scalar(value: object) -> str:
    if value in (None, ""):
        return "N/A"
    return str(value)


def _format_float(value: object, digits: int = 4) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "N/A"
    return f"{numeric:.{digits}f}"


def _format_stage1_filter_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for row in rows:
        formatted.append(
            {
                **row,
                "_passed": _is_true(row.get("passed")),
                "_string": _format_float(row.get("string_combined")),
                "_coexpr_p": _format_pvalue(row.get("census_coexpr_pvalue")),
                "_gene_a_p": _format_pvalue(row.get("census_gene_a_pvalue")),
                "_gene_b_p": _format_pvalue(row.get("census_gene_b_pvalue")),
                "_gene_a_rr": _format_rr(row.get("gene_a_risk_ratio")),
                "_gene_b_rr": _format_rr(row.get("gene_b_risk_ratio")),
                "_coexpr_rr": _format_rr(row.get("coexpr_risk_ratio")),
                "_coexpr_tgt": _format_float(row.get("coexpr_target_pct"), 2),
            }
        )
    formatted.sort(key=lambda row: (not row["_passed"], str(row.get("ligand", ""))))
    return formatted


def _stage1_filter_lookup(rows: list[dict[str, Any]]) -> dict[tuple[str, str], bool]:
    lookup: dict[tuple[str, str], bool] = {}
    for row in rows:
        ligand = _normalize_gene(row.get("ligand"))
        receptor = _normalize_gene(row.get("receptor"))
        if ligand and receptor:
            lookup[(ligand, receptor)] = _is_true(row.get("passed"))
    return lookup


def _dict_list(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _indications_text(value: object) -> str:
    if not isinstance(value, list):
        return "N/A"
    values: list[object | None] = []
    for item in value:
        if isinstance(item, dict):
            values.append(item.get("name") or item.get("efo_term"))
        else:
            values.append(item)
    items = _dedupe_strings(values)
    return ", ".join(items) or "N/A"


def _template_drug(drug: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _safe_text(drug.get("name") or drug.get("drug_name"), "Unknown"),
        "chembl_id": _safe_text(
            drug.get("chembl_id") or drug.get("molecule_chembl_id"),
            "",
        ),
        "moa": _safe_text(
            drug.get("mechanism_of_action") or drug.get("moa"),
            "mechanism not available",
        ),
        "phase": _safe_text(
            drug.get("phase") or drug.get("max_phase"),
            "Preclinical",
        ),
        "indications": _indications_text(drug.get("indications")),
    }


def _split_template_drugs(
    drugs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    clinical: list[dict[str, Any]] = []
    preclinical: list[dict[str, Any]] = []
    for drug in drugs:
        formatted = _template_drug(drug)
        phase = _safe_text(drug.get("phase") or drug.get("max_phase"), "")
        if phase and phase not in {"0", "Preclinical"}:
            clinical.append(formatted)
        else:
            preclinical.append(formatted)
    return clinical, preclinical


def _pathway_parts(pathway_data: dict[str, Any]) -> list[dict[str, str]]:
    parts: list[dict[str, str]] = []
    for role, key in (
        ("ligand", "ligand_pathways"),
        ("receptor", "receptor_pathways"),
    ):
        pathways = pathway_data.get(key, [])
        if isinstance(pathways, list) and pathways:
            parts.append(
                {
                    "role": role,
                    "pathways": "; ".join(str(pathway) for pathway in pathways[:3]),
                }
            )
    return parts


def _direction_from_metric(metric: dict[str, Any]) -> str:
    risk_ratio = _float_or_none(metric.get("risk_ratio"))
    if risk_ratio is not None:
        if risk_ratio > 1:
            return "enriched"
        if risk_ratio < 1:
            return "depleted"

    diff = _float_or_none(metric.get("diff"))
    if diff is not None:
        if diff > 0:
            return "enriched"
        if diff < 0:
            return "depleted"

    return "not determined"


def _stage1_metric_text(metric: dict[str, Any]) -> str:
    return (
        f"RR={_format_stage1_scalar(metric.get('risk_ratio'))}, "
        f"p={_format_stage1_scalar(metric.get('p_value'))}; "
        f"{_direction_from_metric(metric)}"
    )


def _stage1_gene_direction_text(
    ligand: str,
    receptor: str,
    gene_a: dict[str, Any],
    gene_b: dict[str, Any],
) -> str:
    return "; ".join(
        [
            f"{ligand} {_direction_from_metric(gene_a)}",
            f"{receptor} {_direction_from_metric(gene_b)}",
        ]
    )


def _is_at2_celltype(celltype: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", celltype.lower())
    return "at2" in normalized.split() or "alveolar type 2" in normalized


def _hypothesis_use_class(
    *,
    passed: bool | None,
    coexpression_direction: str,
    celltype: str,
) -> str:
    if passed is False:
        return "Negative/contrast only"
    if passed is None:
        return "Cautious support only"
    at2 = _is_at2_celltype(celltype)
    if coexpression_direction == "enriched":
        return "Primary AT2-intrinsic support" if at2 else "Primary target-cell intrinsic support"
    if coexpression_direction == "depleted":
        return "Cross-cell/non-AT2 framing only" if at2 else "Cross-cell/non-target-cell framing only"
    return "Cautious support only"


def _is_epithelial_anchor_text(value: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    normalized = " ".join(normalized.split())
    if not normalized:
        return False
    tokens = set(normalized.split())
    return (
        "at2" in tokens
        or "pulmonary alveolar type 2" in normalized
        or "alveolar type 2" in normalized
        or "alveolar epithelial" in normalized
        or "pulmonary epithelial" in normalized
    )


def _stage1_interpretation(
    *,
    passed: bool | None,
    coexpression_direction: str,
    celltype: str,
) -> str:
    if passed is False:
        return (
            "Failed Stage 1 eligibility. Do not use as primary support; "
            "retain only as negative or contrast evidence."
        )
    if coexpression_direction == "enriched":
        return (
            f"Stage 1 eligible and same-cell coexpression-enriched in {celltype}. "
            "Interpret as a target-cell intrinsic spatial program candidate."
        )
    if coexpression_direction == "depleted":
        return (
            f"Stage 1 eligible, but same-cell coexpression is depleted in {celltype}. "
            "Interpret as cross-cell or non-target-cell spatial niche signal."
        )
    return (
        "Stage 1 eligibility is available, but Census coexpression direction is "
        "not determined. Avoid target-cell intrinsic same-cell claims without "
        "additional support."
    )


def _pair_genes(pair_key: str, pair_data: dict[str, Any]) -> tuple[str, str]:
    ligand = _safe_text(pair_data.get("ligand"), "")
    receptor = _safe_text(pair_data.get("receptor"), "")
    if ligand and receptor:
        return ligand, receptor
    delimiter = "^" if "^" in pair_key else "--"
    parts = pair_key.split(delimiter, 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return ligand, receptor


def _template_pair(
    pair_key: str,
    pair_data: dict[str, Any],
    filter_lookup: dict[tuple[str, str], bool],
) -> dict[str, Any]:
    ligand, receptor = _pair_genes(pair_key, pair_data)
    ppi = pair_data.get("string_ppi", {})
    ppi = ppi if isinstance(ppi, dict) else {}
    census_validation = pair_data.get("census_validation", {})
    census_validation = census_validation if isinstance(census_validation, dict) else {}
    target_vs_rest = census_validation.get("target_vs_rest", {})
    target_vs_rest = target_vs_rest if isinstance(target_vs_rest, dict) else {}
    gene_a = target_vs_rest.get("gene_a", {})
    gene_a = gene_a if isinstance(gene_a, dict) else {}
    gene_b = target_vs_rest.get("gene_b", {})
    gene_b = gene_b if isinstance(gene_b, dict) else {}
    coexpression = target_vs_rest.get("coexpression", {})
    coexpression = coexpression if isinstance(coexpression, dict) else {}
    resolved_celltype = _safe_text(
        census_validation.get("resolved_cell_type")
        or census_validation.get("requested_cell_type"),
        "resolved interest cell type",
    )
    lookup_key = (_normalize_gene(ligand), _normalize_gene(receptor))
    stage1_filter = pair_data.get("stage1_filter", {})
    stage1_filter = stage1_filter if isinstance(stage1_filter, dict) else {}
    passed = filter_lookup.get(lookup_key)
    if passed is None and "passed" in stage1_filter:
        passed = _is_true(stage1_filter.get("passed"))
    coexpression_direction = _direction_from_metric(coexpression)

    pair = {
        "ligand": ligand,
        "receptor": receptor,
        "pair_file": f"stage1_{ligand}--{receptor}.json",
        "score": ppi.get("max_combined_score", "N/A"),
        "interaction": (
            "confirmed" if _is_true(ppi.get("interaction_found")) else "not found"
        ),
        "kegg": _pathway_parts(
            pair_data.get("kegg_pathways", {})
            if isinstance(pair_data.get("kegg_pathways"), dict)
            else {}
        ),
        "reactome": _pathway_parts(
            pair_data.get("reactome_pathways", {})
            if isinstance(pair_data.get("reactome_pathways"), dict)
            else {}
        ),
        "census_rr": coexpression.get("risk_ratio"),
        "census_p": coexpression.get("p_value", "N/A"),
        "resolved_celltype": resolved_celltype,
        "stage1_status": "PASS" if passed else "FAIL" if passed is False else "N/A",
        "stage1_string": (
            f"{'PASS' if passed else 'FAIL' if passed is False else 'N/A'}; "
            f"STRING={_format_stage1_scalar(ppi.get('max_combined_score'))}; "
            f"{'confirmed' if _is_true(ppi.get('interaction_found')) else 'not found'}"
        ),
        "census_coexpression": _stage1_metric_text(coexpression),
        "_coexpression_direction": coexpression_direction,
        "gene_direction": _stage1_gene_direction_text(ligand, receptor, gene_a, gene_b),
        "interpretation": _stage1_interpretation(
            passed=passed,
            coexpression_direction=coexpression_direction,
            celltype=resolved_celltype,
        ),
        "hypothesis_use": _hypothesis_use_class(
            passed=passed,
            coexpression_direction=coexpression_direction,
            celltype=resolved_celltype,
        ),
        "_target_cell_intrinsic_support": (
            passed is True
            and coexpression_direction == "enriched"
        ),
        "_epithelial_intrinsic_support": (
            passed is not False
            and coexpression_direction == "enriched"
            and _is_epithelial_anchor_text(resolved_celltype)
        ),
    }
    if passed is not None:
        pair["_passed"] = passed
    return pair


_STAGE1_REPORT_REF_RE = re.compile(
    r"(stage1_[A-Za-z0-9-]+--[A-Za-z0-9-]+\.json)"
)


def _stage1_ref_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = _STAGE1_REPORT_REF_RE.search(value)
    return match.group(1) if match else None


def _stage1_pair_file_lookup(
    stage1_pairs: dict[str, Any],
    filter_lookup: dict[tuple[str, str], bool],
) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for pair_key, pair_data in stage1_pairs.items():
        if not isinstance(pair_data, dict):
            continue
        pair = _template_pair(pair_key, pair_data, filter_lookup)
        ligand = _safe_text(pair.get("ligand"), "")
        receptor = _safe_text(pair.get("receptor"), "")
        if not ligand or not receptor:
            continue
        lookup[f"stage1_{ligand}--{receptor}.json"] = pair
        lookup[f"stage1_{receptor}--{ligand}.json"] = pair
    return lookup


def _hypothesis_mentions_epithelial_anchor(hypothesis: dict[str, Any]) -> bool:
    entities = hypothesis.get("biological_entities")
    if isinstance(entities, dict):
        cell_types = entities.get("cell_types")
        if isinstance(cell_types, list) and any(
            _is_epithelial_anchor_text(cell_type) for cell_type in cell_types
        ):
            return True
    fields = (
        hypothesis.get("title", ""),
        hypothesis.get("core_claim", ""),
        hypothesis.get("falsifiable_prediction", ""),
        hypothesis.get("validation_approach", ""),
    )
    return any(_is_epithelial_anchor_text(field) for field in fields)


def _normalized_anchor_text(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return " ".join(normalized.split())


def _celltype_anchor_labels(celltype_context: dict[str, Any]) -> list[str]:
    generic_labels = {
        "interest cell",
        "resolved interest cell type",
        "interest cell type",
        "target cell",
        "target cell type",
    }
    labels: list[str] = []
    for key in ("input_label", "resolved_label", "focus_proxy_label"):
        label = _normalized_anchor_text(celltype_context.get(key))
        if not label or label in generic_labels:
            continue
        if label not in labels:
            labels.append(label)
    return labels


def _hypothesis_mentions_celltype_anchor(
    hypothesis: dict[str, Any],
    *,
    celltype_context: dict[str, Any],
) -> bool:
    if _is_true(celltype_context.get("legacy_at2_fallback")):
        return _hypothesis_mentions_epithelial_anchor(hypothesis)

    anchor_labels = _celltype_anchor_labels(celltype_context)
    if not anchor_labels:
        return False

    values: list[Any] = []
    entities = hypothesis.get("biological_entities")
    if isinstance(entities, dict):
        cell_types = entities.get("cell_types")
        if isinstance(cell_types, list):
            values.extend(cell_types)
    values.extend(
        [
            hypothesis.get("title", ""),
            hypothesis.get("core_claim", ""),
            hypothesis.get("falsifiable_prediction", ""),
            hypothesis.get("validation_approach", ""),
        ]
    )

    for value in values:
        text = _normalized_anchor_text(value)
        if text and any(label in text for label in anchor_labels):
            return True
    return False


def _hypothesis_stage1_pairs(
    hypothesis: dict[str, Any],
    stage1_pair_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    refs = hypothesis.get("evidence_references")
    if not isinstance(refs, list):
        return []
    pairs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        token = _stage1_ref_token(ref)
        if not token or token in seen:
            continue
        seen.add(token)
        pair = stage1_pair_lookup.get(token)
        if pair:
            pairs.append(pair)
    return pairs


def _reference_list(hypothesis: dict[str, Any]) -> list[str]:
    refs = hypothesis.get("evidence_references")
    if not isinstance(refs, list):
        return []
    return [ref for ref in refs if isinstance(ref, str) and ref.strip()]


def _ref_is_stage1(ref: str) -> bool:
    return bool(_stage1_ref_token(ref))


def _ref_is_stage2(ref: str) -> bool:
    normalized = ref.strip()
    return normalized.endswith(".json") and (
        normalized.startswith("ot_")
        or normalized.startswith("gwas_")
        or normalized.startswith("genetics_")
    )


def _ref_is_stage3(ref: str) -> bool:
    normalized = ref.strip()
    return normalized.startswith("stage3_") or normalized in {
        "known_drugs.json",
        "resolved_drugs.json",
    }


def _gene_from_gene_level_ref(ref: str) -> str | None:
    name = Path(ref.strip()).name
    if not name.endswith(".json"):
        return None
    stem = name.removesuffix(".json")
    for prefix in ("ot_", "gwas_", "genetics_", "stage3_"):
        if stem.startswith(prefix) and len(stem) > len(prefix):
            return stem[len(prefix) :]
    return None


def _asymmetric_gene_level_support_constraint(
    stage1_pair_evidence: list[dict[str, Any]],
    references: list[str],
) -> str | None:
    support_labels_by_gene: dict[str, set[str]] = {}
    for ref in references:
        gene = _gene_from_gene_level_ref(ref)
        if not gene:
            continue
        labels = support_labels_by_gene.setdefault(_normalize_gene(gene), set())
        if _ref_is_stage2(ref):
            labels.add("Stage 2")
        if _ref_is_stage3(ref):
            labels.add("Stage 3")

    for pair in stage1_pair_evidence:
        if pair.get("_passed") is not True:
            continue
        if not _is_true(pair.get("_target_cell_intrinsic_support")):
            continue
        ligand = _safe_text(pair.get("ligand"), "")
        receptor = _safe_text(pair.get("receptor"), "")
        if not ligand or not receptor:
            continue
        ligand_labels = support_labels_by_gene.get(_normalize_gene(ligand), set())
        receptor_labels = support_labels_by_gene.get(_normalize_gene(receptor), set())
        if bool(ligand_labels) == bool(receptor_labels):
            continue
        anchor, context = (
            (ligand, receptor) if ligand_labels else (receptor, ligand)
        )
        anchor_labels = ligand_labels or receptor_labels
        if {"Stage 2", "Stage 3"}.issubset(anchor_labels):
            support_label = "Stage 2/3-supported"
        else:
            support_label = f"{' and '.join(sorted(anchor_labels))}-supported"
        return (
            f"Treat {anchor} as the {support_label} anchor and {context} as a "
            f"coexpression-context partner/readout; do not infer gene-level "
            f"target-disease support or drug actionability for {context} from "
            "this pair."
        )
    return None


def _remove_framing_pairs_from_gap_analysis(
    hypothesis_data: dict[str, Any],
    framing_pairs: list[dict[str, str]],
) -> None:
    gap_analysis = hypothesis_data.get("gap_analysis")
    if not isinstance(gap_analysis, dict) or not framing_pairs:
        return
    covered_sources = {
        pair.get("source", "") for pair in framing_pairs if pair.get("source")
    }
    orphan_files = gap_analysis.get("orphan_files")
    if not isinstance(orphan_files, list):
        return
    filtered_orphans = [
        orphan for orphan in orphan_files if str(orphan) not in covered_sources
    ]
    removed_count = len(orphan_files) - len(filtered_orphans)
    if removed_count <= 0:
        return
    gap_analysis = dict(gap_analysis)
    gap_analysis["orphan_files"] = filtered_orphans
    referenced_files = _float_or_none(gap_analysis.get("referenced_files"))
    total_files = _float_or_none(gap_analysis.get("total_evidence_files"))
    if referenced_files is not None:
        gap_analysis["referenced_files"] = int(referenced_files) + removed_count
    if total_files:
        gap_analysis["evidence_coverage_pct"] = round(
            100.0 * float(gap_analysis.get("referenced_files", 0)) / total_files,
            2,
        )
        hypothesis_data["evidence_coverage_pct"] = gap_analysis[
            "evidence_coverage_pct"
        ]
    hypothesis_data["gap_analysis"] = gap_analysis


def _secondary_stage1_framing_pair(
    pair: dict[str, Any],
    *,
    celltype_context: dict[str, Any],
) -> dict[str, str] | None:
    if pair.get("_passed") is not True:
        return None
    if _is_true(pair.get("_target_cell_intrinsic_support")):
        return None
    source = _safe_text(pair.get("pair_file"), "")
    if not source:
        return None
    usage = _safe_text(
        celltype_context.get("secondary_usage"),
        "Cross-cell/spatial-niche framing only; not interest-cell-intrinsic support",
    )
    ligand = _safe_text(pair.get("ligand"), "")
    receptor = _safe_text(pair.get("receptor"), "")
    return {
        "pair": f"{ligand}-{receptor}" if ligand and receptor else source,
        "census_direction": _safe_text(
            pair.get("_coexpression_direction"),
            "not determined",
        ),
        "usage": usage,
        "source": source,
    }


def _annotate_hypothesis_tiers(
    hypotheses: list[Any],
    *,
    stage1_pair_lookup: dict[str, dict[str, Any]],
    hypothesis_interpretations: dict[str, Any],
    celltype_context: dict[str, Any],
) -> tuple[
    list[Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, str]],
]:
    rendered_hypotheses: list[Any] = []
    primary: list[dict[str, Any]] = []
    secondary: list[dict[str, Any]] = []
    gene_level: list[dict[str, Any]] = []
    secondary_stage1_framing_pairs: list[dict[str, str]] = []
    seen_secondary_sources: set[str] = set()
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, dict):
            rendered_hypotheses.append(hypothesis)
            continue
        rendered_hypothesis = dict(hypothesis)
        rank = str(rendered_hypothesis.get("rank") or "")
        snippets = hypothesis_interpretations.get(rank, {})
        snippets = snippets if isinstance(snippets, dict) else {}
        implication = snippets.get("implication")
        if isinstance(implication, str) and implication.strip():
            rendered_hypothesis["_interpretation"] = implication

        stage1_pair_evidence = _hypothesis_stage1_pairs(
            rendered_hypothesis,
            stage1_pair_lookup,
        )
        references = _reference_list(rendered_hypothesis)
        biological_grounding_refs = [
            ref for ref in references if _ref_is_stage1(ref) or "spatial" in ref.lower()
        ]
        target_disease_support_refs = [ref for ref in references if _ref_is_stage2(ref)]
        actionability_refs = [ref for ref in references if _ref_is_stage3(ref)]
        rendered_hypothesis["_biological_grounding_refs"] = biological_grounding_refs
        rendered_hypothesis["_target_disease_support_refs"] = target_disease_support_refs
        rendered_hypothesis["_actionability_refs"] = actionability_refs
        has_primary_target_cell_support = any(
            _is_true(pair.get("_target_cell_intrinsic_support"))
            for pair in stage1_pair_evidence
        )
        mentions_target_cell_anchor = _hypothesis_mentions_celltype_anchor(
            rendered_hypothesis,
            celltype_context=celltype_context,
        )
        if has_primary_target_cell_support and mentions_target_cell_anchor:
            rendered_hypothesis["_tier"] = "primary_target_cell_intrinsic"
            rendered_hypothesis["_tier_label"] = _safe_text(
                celltype_context.get("primary_tier_label"),
                "Primary interest-cell intrinsic",
            )
            rendered_hypothesis["_tier_note"] = _safe_text(
                celltype_context.get("primary_tier_note"),
                "Cited Stage 1 Census evidence supports same-cell coexpression enrichment.",
            )
            interpretation_constraint = _safe_text(
                celltype_context.get("primary_constraint"),
                "Interest-cell same-cell coexpression enrichment supports target-cell context, but not causal mechanism.",
            )
            asymmetric_constraint = _asymmetric_gene_level_support_constraint(
                stage1_pair_evidence,
                references,
            )
            if asymmetric_constraint:
                interpretation_constraint = (
                    f"{interpretation_constraint} {asymmetric_constraint}"
                )
            rendered_hypothesis["_interpretation_constraint"] = (
                interpretation_constraint
            )
            primary.append(rendered_hypothesis)
        elif not biological_grounding_refs:
            rendered_hypothesis["_tier"] = "gene_level_actionability"
            rendered_hypothesis["_tier_label"] = _safe_text(
                celltype_context.get("gene_level_tier_label"),
                "Gene-level/actionability follow-up",
            )
            rendered_hypothesis["_tier_note"] = _safe_text(
                celltype_context.get("gene_level_tier_note"),
                "Cited evidence provides target-disease or actionability "
                "context, but no Stage 1/spatial grounding was cited.",
            )
            rendered_hypothesis["_interpretation_constraint"] = _safe_text(
                celltype_context.get("gene_level_constraint"),
                "Gene-level support only; do not interpret as interest-cell-intrinsic or spatial-niche evidence.",
            )
            gene_level.append(rendered_hypothesis)
        else:
            rendered_hypothesis["_tier"] = "secondary_spatial_niche"
            rendered_hypothesis["_tier_label"] = _safe_text(
                celltype_context.get("secondary_tier_label"),
                "Secondary spatial-niche/cross-cell",
            )
            rendered_hypothesis["_tier_note"] = _safe_text(
                celltype_context.get("secondary_tier_note"),
                "Treat as spatially colocalized or cross-cell niche biology, not as an interest-cell-intrinsic target mechanism.",
            )
            rendered_hypothesis["_interpretation_constraint"] = _safe_text(
                celltype_context.get("secondary_constraint"),
                "Use as cross-cell/spatial-niche follow-up evidence only; do not interpret as interest-cell-intrinsic support.",
            )
            for pair in stage1_pair_evidence:
                framing_pair = _secondary_stage1_framing_pair(
                    pair,
                    celltype_context=celltype_context,
                )
                if not framing_pair:
                    continue
                source = framing_pair["source"]
                if source in seen_secondary_sources:
                    continue
                seen_secondary_sources.add(source)
                secondary_stage1_framing_pairs.append(framing_pair)
            secondary.append(rendered_hypothesis)
        rendered_hypotheses.append(rendered_hypothesis)

    for index, hypothesis in enumerate(primary, start=1):
        hypothesis["_tier_rank"] = index
    for index, hypothesis in enumerate(secondary, start=1):
        hypothesis["_tier_rank"] = index
    for index, hypothesis in enumerate(gene_level, start=1):
        hypothesis["_tier_rank"] = index
    return (
        rendered_hypotheses,
        primary,
        secondary,
        gene_level,
        secondary_stage1_framing_pairs,
    )


def _template_pairs_for_gene(
    gene: str,
    stage1_pairs: dict[str, Any],
    filter_lookup: dict[tuple[str, str], bool],
) -> list[dict[str, Any]]:
    normalized_gene = _normalize_gene(gene)
    pairs: list[dict[str, Any]] = []
    for pair_key, pair_data in stage1_pairs.items():
        if not isinstance(pair_data, dict):
            continue
        ligand, receptor = _pair_genes(pair_key, pair_data)
        if normalized_gene not in {_normalize_gene(ligand), _normalize_gene(receptor)}:
            continue
        pairs.append(_template_pair(pair_key, pair_data, filter_lookup))
    return pairs


def _candidate_row(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "gene": candidate.get("gene"),
        **{
            field: _score(candidate, field)
            for field in _SCORE_FIELDS
        },
        "classification": candidate.get("classification", "unknown"),
        "priority": candidate.get("priority", "unranked"),
        "stage3_candidate": candidate.get("stage3_candidate", False),
    }


def _normalize_template_interpretations(
    interpretations: dict[str, Any],
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in (
        "executive_summary_opportunities",
        "scoring_landscape",
        "stage1_filter",
        "hypotheses_overview",
        "final_recommendations",
    ):
        value = interpretations.get(key)
        if isinstance(value, str) and value.strip():
            normalized[key] = value

    for key in ("candidates", "hypotheses"):
        value = interpretations.get(key)
        if isinstance(value, dict):
            normalized[key] = value

    return normalized


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence) and not isinstance(
        value,
        (bytes, bytearray, str),
    ):
        for item in value:
            text = _first_text(item)
            if text:
                return text
        return ""
    if value is None:
        return ""
    return str(value).strip()


def _labels_equal(left: str, right: str) -> bool:
    return " ".join(left.casefold().split()) == " ".join(
        right.casefold().split()
    )


def _celltype_context_from_template_context(
    template_context: dict[str, Any],
) -> dict[str, str | bool]:
    celltype_resolution = template_context.get("celltype_resolution", {})
    celltype_resolution = (
        celltype_resolution if isinstance(celltype_resolution, dict) else {}
    )
    input_label_raw = _first_text(
        celltype_resolution.get("primary_input_celltype")
    ) or _first_text(celltype_resolution.get("interest_celltypes"))
    resolved_label_raw = _first_text(
        celltype_resolution.get("primary_resolved_celltype")
    )
    has_explicit_celltype_resolution = bool(input_label_raw or resolved_label_raw)
    match_mode = _first_text(celltype_resolution.get("primary_match_mode"))

    if not resolved_label_raw:
        stage1_pairs = template_context.get("stage1_pairs", {})
        stage1_pairs = stage1_pairs if isinstance(stage1_pairs, dict) else {}
        for pair_data in stage1_pairs.values():
            if not isinstance(pair_data, dict):
                continue
            census_validation = pair_data.get("census_validation", {})
            census_validation = (
                census_validation
                if isinstance(census_validation, dict)
                else {}
            )
            resolved_label_raw = _first_text(
                census_validation.get("resolved_cell_type")
            ) or _first_text(census_validation.get("requested_cell_type"))
            if resolved_label_raw:
                break

    default_label = "interest cell"
    input_label = input_label_raw or default_label
    resolved_label = resolved_label_raw or input_label_raw or default_label
    is_proxy = (
        bool(input_label_raw)
        and bool(resolved_label_raw)
        and match_mode == "semantic_proxy"
        and not _labels_equal(input_label_raw, resolved_label_raw)
    )
    if is_proxy:
        focus_detail = f"{input_label_raw}; Census proxy: {resolved_label_raw}"
        focus_proxy_label = f"{resolved_label_raw.replace(' ', '-')} proxy"
        focus_short = f"interest-cell / {focus_proxy_label}"
    else:
        focus_detail = resolved_label_raw or input_label_raw or default_label
        focus_proxy_label = ""
        focus_short = focus_detail.replace(" ", "-")

    legacy_at2_fallback = (
        not has_explicit_celltype_resolution
        and bool(resolved_label_raw)
        and _is_epithelial_anchor_text(resolved_label_raw)
    )
    context: dict[str, str | bool] = {
        "input_label": input_label,
        "resolved_label": resolved_label,
        "match_mode": match_mode,
        "is_proxy": is_proxy,
        "focus_detail": focus_detail,
        "focus_short": focus_short,
        "focus_proxy_label": focus_proxy_label,
        "legacy_at2_fallback": legacy_at2_fallback,
        "primary_heading": "Primary Interest-Cell Follow-up Candidates",
        "primary_tier_label": "Primary interest-cell intrinsic",
        "primary_tier_note": (
            "Cited Stage 1 Census evidence supports same-cell coexpression "
            f"enrichment for {focus_detail} ({focus_short})."
        ),
        "primary_constraint": (
            f"Same-cell coexpression enrichment for {focus_detail} supports "
            "target-cell context, but not causal mechanism."
        ),
        "secondary_tier_label": "Secondary spatial-niche/cross-cell",
        "secondary_tier_note": (
            "Treat as spatially colocalized or cross-cell niche biology "
            f"linked to {focus_detail}, not as an interest-cell-intrinsic "
            "target mechanism."
        ),
        "secondary_constraint": (
            "Use as cross-cell/spatial-niche follow-up evidence only; do "
            "not interpret as interest-cell-intrinsic support."
        ),
        "gene_level_tier_label": "Gene-level/actionability follow-up",
        "gene_level_tier_note": (
            "Cited evidence provides target-disease or actionability "
            "context, but no Stage 1/spatial grounding was cited."
        ),
        "gene_level_constraint": (
            "Gene-level support only; do not interpret as "
            "interest-cell-intrinsic or spatial-niche evidence for "
            f"{focus_detail}."
        ),
        "secondary_usage": (
            "Cross-cell/spatial-niche framing only; not "
            "interest-cell-intrinsic support"
        ),
    }
    if legacy_at2_fallback:
        context.update(
            {
                "focus_detail": "epithelial/AT2 cell context",
                "focus_short": "AT2/epithelial",
                "primary_heading": "Primary AT2/Epithelial Follow-up Candidates",
                "primary_tier_label": "Primary epithelial/AT2-intrinsic",
                "primary_tier_note": (
                    "Cited Stage 1 Census evidence supports same-cell "
                    "coexpression enrichment in the resolved epithelial/AT2 "
                    "cell context."
                ),
                "primary_constraint": (
                    "AT2/epithelial same-cell coexpression enrichment "
                    "supports target-cell context, but not causal mechanism."
                ),
                "secondary_heading": "Secondary Spatial-Niche Follow-up Candidates",
                "secondary_tier_label": "Secondary epithelial-associated niche",
                "secondary_tier_note": (
                    "Treat as spatially colocalized non-epithelial or "
                    "cross-cell niche biology linked to the epithelial "
                    "program, not as an epithelial-cell-intrinsic target "
                    "mechanism."
                ),
                "secondary_constraint": (
                    "Use as cross-cell/spatial-niche follow-up evidence only; "
                    "do not interpret as AT2-intrinsic support."
                ),
                "gene_level_constraint": (
                    "Gene-level support only; do not interpret as "
                    "AT2-intrinsic or spatial-niche evidence."
                ),
                "secondary_usage": (
                    "Cross-cell/spatial-niche framing only; not "
                    "AT2-intrinsic support"
                ),
            }
        )
    return context


def _markdown_template_context(
    report_data: dict[str, Any],
    interpretations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    interpretations = interpretations if isinstance(interpretations, dict) else {}
    interpretations = _normalize_template_interpretations(interpretations)
    raw_candidates = report_data.get("candidates", [])
    candidates = _dict_list(raw_candidates)
    selected = [candidate for candidate in candidates if candidate.get("stage3_candidate")]
    selected = selected or candidates[:5]
    stage3_genes = [
        _safe_text(candidate.get("gene"), "")
        for candidate in selected
        if candidate.get("gene")
    ]

    template_context = report_data.get("template_context", {})
    template_context = template_context if isinstance(template_context, dict) else {}
    raw_stage1_rows = template_context.get("stage1_filter_results", [])
    stage1_rows = _dict_list(raw_stage1_rows)
    stage1_pairs = template_context.get("stage1_pairs", {})
    stage1_pairs = stage1_pairs if isinstance(stage1_pairs, dict) else {}
    filter_lookup = _stage1_filter_lookup(stage1_rows)
    stage1_pair_lookup = _stage1_pair_file_lookup(stage1_pairs, filter_lookup)
    celltype_context = _celltype_context_from_template_context(template_context)

    featured_cards: list[dict[str, Any]] = []
    for candidate in selected:
        clinical = [
            _template_drug(drug)
            for drug in _dict_list(candidate.get("clinical_drugs", []))
        ]
        preclinical = [
            _template_drug(drug)
            for drug in _dict_list(candidate.get("preclinical_drugs", []))
        ]
        if not clinical and not preclinical:
            drugs = _dict_list(candidate.get("drugs", []))
            clinical, preclinical = _split_template_drugs(drugs)
        gene = _safe_text(candidate.get("gene"), "")
        pairs = _template_pairs_for_gene(gene, stage1_pairs, filter_lookup)
        stage1_celltype = next(
            (
                str(pair.get("resolved_celltype"))
                for pair in pairs
                if pair.get("resolved_celltype")
            ),
            "resolved interest cell type",
        )
        card = {
            "gene": gene,
            "rubric": _candidate_row(candidate),
            "_clinical_drugs": clinical,
            "_preclinical_compounds": preclinical,
            "_pairs": pairs,
            "_stage1_celltype": stage1_celltype,
        }
        candidate_interpretations = interpretations.get("candidates", {})
        candidate_interpretations = (
            candidate_interpretations
            if isinstance(candidate_interpretations, dict)
            else {}
        )
        snippets = candidate_interpretations.get(gene.upper(), {})
        snippets = snippets if isinstance(snippets, dict) else {}
        card_interpretations = {
            key: snippets[key]
            for key in ("drug_profile", "biological_context", "recommendation")
            if isinstance(snippets.get(key), str) and snippets[key].strip()
        }
        if card_interpretations:
            card["_interpretations"] = card_interpretations
        featured_cards.append(card)

    hypothesis_data = template_context.get("hypothesis_data", {})
    hypothesis_data = hypothesis_data if isinstance(hypothesis_data, dict) else {}
    hypothesis_data = dict(hypothesis_data)
    hypotheses = hypothesis_data.get("hypotheses")
    if isinstance(hypotheses, list):
        hypothesis_interpretations = interpretations.get("hypotheses", {})
        hypothesis_interpretations = (
            hypothesis_interpretations
            if isinstance(hypothesis_interpretations, dict)
            else {}
        )
        (
            rendered_hypotheses,
            primary_hypotheses,
            secondary_hypotheses,
            gene_level_hypotheses,
            secondary_stage1_framing_pairs,
        ) = (
            _annotate_hypothesis_tiers(
                hypotheses,
                stage1_pair_lookup=stage1_pair_lookup,
                hypothesis_interpretations=hypothesis_interpretations,
                celltype_context=celltype_context,
            )
        )
        hypothesis_data["hypotheses"] = rendered_hypotheses
        hypothesis_data["primary_hypotheses"] = primary_hypotheses
        hypothesis_data["secondary_hypotheses"] = secondary_hypotheses
        hypothesis_data["gene_level_hypotheses"] = gene_level_hypotheses
        hypothesis_data["secondary_stage1_framing_pairs"] = (
            secondary_stage1_framing_pairs
        )
        _remove_framing_pairs_from_gap_analysis(
            hypothesis_data,
            secondary_stage1_framing_pairs,
        )
    return {
        "disease": _safe_text(report_data.get("disease"), "unspecified disease"),
        "n_genes": len(candidates),
        "n_featured": len(stage3_genes),
        "stage3_genes": stage3_genes,
        "featured_cards": featured_cards,
        "featured_rows": [_candidate_row(candidate) for candidate in selected],
        "other_rows": [
            _candidate_row(candidate)
            for candidate in candidates
            if candidate not in selected
        ],
        "stage1_filter_results": _format_stage1_filter_results(stage1_rows),
        "hypothesis_data": hypothesis_data,
        "celltype_context": celltype_context,
        "disease_scope": {"requires_proxy_note": False},
        "data_limitations": [],
        "novelty_opportunity_legend": NOVELTY_OPPORTUNITY_LEGEND,
        "interpretations": interpretations,
    }


def _strip_expand_markers(markdown: str) -> str:
    stripped = re.sub(r"^[ \t]*<!--\s*EXPAND:.*?-->\s*$", "", markdown, flags=re.MULTILINE)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip() + "\n"


def render_report_html(report_data: dict[str, Any], markdown: str) -> str:
    disease = _safe_text(report_data.get("disease"), "unspecified disease")
    title = f"Therapeutic Target Assessment Report - {disease}"
    sources = report_data.get("sources", {})
    source_count = len(sources) if isinstance(sources, dict) else 0
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"  <title>{escape(title)}</title>",
            (
                "  <style>"
                "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
                "line-height:1.5;margin:2rem;max-width:1100px}"
                "pre{white-space:pre-wrap;background:#fafafa;border:1px solid #ddd;"
                "padding:1rem;overflow:auto}"
                "code{background:#f3f3f3;padding:0.1rem 0.25rem}"
                "</style>"
            ),
            "</head>",
            "<body>",
            f"  <h1>{escape(title)}</h1>",
            (
                "  <p><strong>Schema:</strong> "
                f"{escape(str(report_data.get('schema_version', 'unknown')))}"
                f" | <strong>Sources:</strong> {source_count}</p>"
            ),
            f"  <pre>{escape(markdown)}</pre>",
            "</body>",
            "</html>",
            "",
        ]
    )


def _score(candidate: dict[str, Any], field: str) -> object:
    scores = candidate.get("scores", {})
    if isinstance(scores, dict):
        return scores.get(field, _score_field_default(field))
    return _score_field_default(field)


def _score_field_default(field: str) -> object:
    if field in _GWAS_AUDIT_FIELD_DEFAULTS:
        return _GWAS_AUDIT_FIELD_DEFAULTS[field]
    if field in _TRACTABILITY_AUDIT_FIELD_DEFAULTS:
        return _TRACTABILITY_AUDIT_FIELD_DEFAULTS[field]
    if field in _SAFETY_AUDIT_FIELD_DEFAULTS:
        return _SAFETY_AUDIT_FIELD_DEFAULTS[field]
    if field in _BIOLOGICAL_AUDIT_FIELD_DEFAULTS:
        return _BIOLOGICAL_AUDIT_FIELD_DEFAULTS[field]
    if field in _STAGE1_AUDIT_FIELD_DEFAULTS:
        return _STAGE1_AUDIT_FIELD_DEFAULTS[field]
    if field in _NOVELTY_AUDIT_FIELD_DEFAULTS:
        return _NOVELTY_AUDIT_FIELD_DEFAULTS[field]
    return 0


def _score_field_value(scores: Mapping[str, Any], field: str) -> object:
    if field in scores:
        return scores.get(field)
    if field == "exploratory_rank_total":
        return scores.get("exploratory_total", _score_field_default(field))
    if field == "combined_rank_score":
        return scores.get("combined_total", _score_field_default(field))
    return _score_field_default(field)


def _drug_name(entry: dict[str, Any]) -> str:
    return str(
        entry.get("drug_name")
        or entry.get("name")
        or entry.get("pref_name")
        or entry.get("molecule_pref_name")
        or entry.get("chembl_id")
        or entry.get("molecule_chembl_id")
        or ""
    ).strip()


def _resolved_drug_lookup(base: Path) -> dict[tuple[str, str], dict[str, Any]]:
    path = base / "evidence" / "resolved_drugs.json"
    payload = _load_optional_json(path, [])
    if not isinstance(payload, list):
        return {}

    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        gene = _normalize_gene(row.get("gene"))
        chembl_id = _safe_text(row.get("chembl_id"), "").upper()
        if gene and chembl_id:
            lookup[(gene, chembl_id)] = row
    return lookup


def _disease_names(row: dict[str, Any]) -> list[str]:
    diseases = row.get("diseases")
    values: list[object | None] = []
    if isinstance(diseases, list):
        for item in diseases:
            if not isinstance(item, dict):
                continue
            disease = item.get("disease")
            if isinstance(disease, dict):
                values.append(disease.get("name"))
            values.append(item.get("diseaseFromSource"))
    return _dedupe_strings(values)


def _clinical_drugs_from_opentargets(
    base: Path,
    gene: str,
    resolved_lookup: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], bool]:
    path = base / "evidence" / f"ot_{gene}.json"
    sources = [f"evidence/ot_{gene}.json"] if path.exists() else []
    if not path.exists():
        return [], sources, False

    payload = _load_optional_json(path, {})
    if not isinstance(payload, dict):
        return [], sources, False
    target_drugs = payload.get("target_drugs")
    if not isinstance(target_drugs, dict):
        return [], sources, False
    rows = target_drugs.get("rows")
    if not isinstance(rows, list):
        return [], sources, False

    drugs: list[dict[str, Any]] = []
    seen: set[str] = set()
    used_resolved_drug = False
    normalized_gene = _normalize_gene(gene)
    for row in rows:
        if not isinstance(row, dict):
            continue
        drug = row.get("drug")
        if not isinstance(drug, dict):
            continue
        chembl_id = _safe_text(drug.get("id"), "").upper()
        if not chembl_id or chembl_id in seen:
            continue
        seen.add(chembl_id)
        resolved = resolved_lookup.get((normalized_gene, chembl_id), {})
        used_resolved_drug = used_resolved_drug or bool(resolved)
        drugs.append(
            {
                "name": _safe_text(
                    resolved.get("resolved_name") or drug.get("name"),
                    chembl_id,
                ),
                "chembl_id": chembl_id,
                "phase": row.get("maxClinicalStage")
                or drug.get("maximumClinicalStage"),
                "first_approval": resolved.get("first_approval"),
                "mechanism_of_action": resolved.get("mechanism_of_action"),
                "indications": _disease_names(row),
                "source": "opentargets",
            }
        )
    return drugs, sources, used_resolved_drug


def _drug_records_from_stage3(stage3: dict[str, Any]) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = [stage3]
    chembl = stage3.get("chembl")
    if isinstance(chembl, dict):
        containers.append(chembl)

    raw_records: list[dict[str, Any]] = []
    for container in containers:
        for key in (
            "matched_drugs",
            "chembl_drugs",
            "preclinical_compounds",
            "chembl_records",
        ):
            value = container.get(key)
            if isinstance(value, dict):
                value = value.get("matched_drugs", [])
            if isinstance(value, list):
                raw_records.extend(item for item in value if isinstance(item, dict))

    drugs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in raw_records:
        name = _drug_name(record)
        if not name or name in seen:
            continue
        seen.add(name)
        indications = record.get("indications")
        if not isinstance(indications, list):
            indications = [record.get("indication")] if record.get("indication") else []
        drugs.append(
            {
                "name": name,
                "chembl_id": str(
                    record.get("chembl_id")
                    or record.get("molecule_chembl_id")
                    or ""
                ).strip(),
                "phase": record.get("max_phase"),
                "first_approval": record.get("first_approval"),
                "mechanism_of_action": record.get("mechanism_of_action"),
                "indications": _dedupe_strings(indications),
                "source": "chembl",
            }
        )
    return drugs


def _drop_preclinical_duplicates(
    clinical_drugs: list[dict[str, Any]],
    preclinical_drugs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    clinical_chembl_ids = {
        _safe_text(drug.get("chembl_id"), "").upper()
        for drug in clinical_drugs
        if _safe_text(drug.get("chembl_id"), "")
    }
    if not clinical_chembl_ids:
        return preclinical_drugs
    return [
        drug
        for drug in preclinical_drugs
        if _safe_text(drug.get("chembl_id"), "").upper() not in clinical_chembl_ids
    ]


def build_report_data(
    data_dir: str,
    disease: str,
    hypothesis_data: dict[str, Any] | None = None,
    *,
    hypothesis_source: str | None = None,
) -> dict[str, Any]:
    base = Path(data_dir).expanduser().resolve()
    require_hypothesis_file = hypothesis_data is None
    issues = _missing_required_evidence(
        base,
        require_hypothesis=require_hypothesis_file,
    )
    if issues:
        return _invalid_report_data(base, disease, issues)

    paths = _required_evidence_paths(base)
    try:
        assessment = _load_json(paths["assessment_results"])
    except (json.JSONDecodeError, OSError) as exc:
        return _invalid_report_data(
            base,
            disease,
            [
                _invalid_required_json_issue(
                    base,
                    "assessment_results",
                    paths["assessment_results"],
                    exc,
                )
            ],
        )
    if hypothesis_data is None:
        try:
            hypothesis = _load_json(paths["hypothesis_report"])
        except (json.JSONDecodeError, OSError) as exc:
            return _invalid_report_data(
                base,
                disease,
                [
                    _invalid_required_json_issue(
                        base,
                        "hypothesis_report",
                        paths["hypothesis_report"],
                        exc,
                    )
                ],
            )
        hypothesis_source = "evidence/hypothesis_report.json"
    else:
        hypothesis = hypothesis_data.get("hypothesis_report", hypothesis_data)
        hypothesis_source = hypothesis_source or "drug.md"
    if not isinstance(assessment, dict):
        return _invalid_report_data(
            base,
            disease,
            [
                {
                    "code": "INVALID_ASSESSMENT_SHAPE",
                    "severity": "critical",
                    "message": "assessment_results.json must be a JSON object",
                    "path": "evidence/assessment_results.json",
                }
            ],
        )
    if not isinstance(hypothesis, dict):
        path = (
            "evidence/hypothesis_report.json"
            if hypothesis_data is None
            else "drug.md"
        )
        message = (
            "hypothesis_report.json must be a JSON object"
            if hypothesis_data is None
            else "injected hypothesis_data must be a JSON object"
        )
        return _invalid_report_data(
            base,
            disease,
            [
                {
                    "code": "INVALID_HYPOTHESIS_SHAPE",
                    "severity": "critical",
                    "message": message,
                    "path": path,
                }
            ],
        )
    rows, assessment_issues = _assessment_rows(assessment)
    if assessment_issues:
        return _invalid_report_data(base, disease, assessment_issues)
    selected_genes = _stage3_genes(assessment, rows)
    resolved_lookup = _resolved_drug_lookup(base)
    resolved_path = base / "evidence" / "resolved_drugs.json"
    stage1_filter_results = _load_stage1_filter_results(base)
    stage1_pairs = _load_optional_dict(base / "evidence" / "stage1_evidence.json")
    celltype_resolution = _load_optional_json(
        base / "evidence" / "celltype_resolution.json",
        {},
    )
    if not isinstance(celltype_resolution, dict):
        celltype_resolution = {}

    candidates: list[dict[str, Any]] = []
    for row in sorted(
        rows,
        key=lambda item: (
            -float(item.get("combined_rank_score", item.get("combined_total", item.get("validated_score", 0))) or 0),
            -float(item.get("combined_total", item.get("validated_score", 0)) or 0),
            _normalize_gene(item.get("gene")),
        ),
    ):
        gene = _normalize_gene(row.get("gene"))
        if not gene:
            continue
        stage3_path = base / "evidence" / f"stage3_{gene}.json"
        sources = ["evidence/assessment_results.json"]
        (
            clinical_drugs,
            clinical_sources,
            used_resolved_drug,
        ) = _clinical_drugs_from_opentargets(
            base,
            gene,
            resolved_lookup,
        )
        for source in clinical_sources:
            if source not in sources:
                sources.append(source)
        if used_resolved_drug and resolved_path.exists():
            resolved_source = "evidence/resolved_drugs.json"
            if resolved_source not in sources:
                sources.append(resolved_source)
        preclinical_drugs: list[dict[str, Any]] = []
        if stage3_path.exists():
            sources.append(f"evidence/stage3_{gene}.json")
            stage3_payload = _load_optional_json(stage3_path, {})
            if isinstance(stage3_payload, dict):
                preclinical_drugs = _drug_records_from_stage3(stage3_payload)
        preclinical_drugs = _drop_preclinical_duplicates(
            clinical_drugs,
            preclinical_drugs,
        )
        drugs = clinical_drugs + preclinical_drugs
        candidates.append(
            {
                "gene": gene,
                "classification": row.get("classification", "unknown"),
                "priority": row.get("priority", "unranked"),
                "stage3_candidate": gene in selected_genes,
                "scores": {
                    field: _score_field_value(row, field)
                    for field in _SCORE_FIELDS
                },
                "clinical_drug_count": len(clinical_drugs),
                "preclinical_drug_count": len(preclinical_drugs),
                "drug_count": len(drugs),
                "clinical_drugs": clinical_drugs,
                "preclinical_drugs": preclinical_drugs,
                "drugs": drugs,
                "sources": sources,
            }
        )

    hypotheses = hypothesis.get("hypotheses")
    if not isinstance(hypotheses, list):
        hypotheses = []

    sections = {
        "executive_summary": {
            "title": "Executive Summary",
            "sources": ["evidence/assessment_results.json"],
        },
        "druggability_matrix": {
            "title": "Target Druggability Matrix",
            "sources": ["evidence/assessment_results.json"],
        },
        "candidate_deep_dives": {
            "title": "Candidate Deep Dives",
            "sources": sorted(
                {
                    source
                    for candidate in candidates
                    for source in candidate["sources"]
                }
            ),
        },
        "hypotheses": {
            "title": "Mechanistic Hypotheses",
            "sources": [hypothesis_source],
        },
    }

    cited_sources: set[str] = set()
    for section in sections.values():
        section_sources = section.get("sources", [])
        if isinstance(section_sources, list):
            cited_sources.update(
                source for source in section_sources if isinstance(source, str)
            )
    cited_sources.update(
        source
        for candidate in candidates
        for source in candidate["sources"]
        if isinstance(source, str)
    )
    cited_sources.update(
        {
            "evidence/assessment_results.json",
            hypothesis_source,
        }
    )
    for optional_source in (
        "evidence/stage1_filter_results.json",
        "evidence/stage1_filter_results.csv",
        "evidence/stage1_evidence.json",
        "evidence/celltype_resolution.json",
    ):
        if (base / optional_source).exists():
            cited_sources.add(optional_source)

    return {
        "schema_version": "drug_target.report_data.v1",
        "valid": True,
        "created_at": _utc_now(),
        "data_dir": str(base),
        "disease": disease or assessment.get("disease") or hypothesis.get("disease") or "",
        "sections": sections,
        "candidates": candidates,
        "hypotheses": hypotheses,
        "sources": {
            source: {"sha256": _sha256_path(base / source)}
            for source in sorted(cited_sources)
            if (base / source).exists()
        },
        "template_context": {
            "stage1_filter_results": stage1_filter_results,
            "stage1_pairs": stage1_pairs,
            "celltype_resolution": celltype_resolution,
            "hypothesis_data": hypothesis,
        },
        "issues": [],
    }


def validate_report_data(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    issues = list(report_data.get("issues") or [])
    if report_data.get("schema_version") != "drug_target.report_data.v1":
        issues.append(
            {
                "code": "INVALID_SCHEMA_VERSION",
                "severity": "critical",
                "message": "report_data schema_version must be drug_target.report_data.v1",
            }
        )
    if not report_data.get("candidates"):
        issues.append(
            {
                "code": "NO_CANDIDATES",
                "severity": "critical",
                "message": "report_data must include at least one candidate",
            }
        )
    if not report_data.get("sections"):
        issues.append(
            {
                "code": "NO_SECTIONS",
                "severity": "critical",
                "message": "report_data must include sections metadata",
            }
        )
    return issues


def _target_assessment_inputs(
    report_data: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    rubric_by_gene: dict[str, dict[str, Any]] = {}
    stage3_data: dict[str, dict[str, Any]] = {}
    stage3_genes: list[str] = []

    for candidate in _dict_list(report_data.get("candidates", [])):
        gene = _normalize_gene(candidate.get("gene"))
        if not gene:
            continue

        scores = candidate.get("scores", {})
        scores = scores if isinstance(scores, dict) else {}
        rubric_by_gene[gene] = {
            **{
                field: _score_field_value(scores, field)
                for field in _SCORE_FIELDS
            },
            "classification": candidate.get("classification", "unknown"),
            "priority": candidate.get("priority", "unranked"),
            "stage3_candidate": candidate.get("stage3_candidate", False),
        }
        stage3_data[gene] = {
            "drugs": _dict_list(candidate.get("drugs", [])),
            "safety_summary": candidate.get("safety_summary")
            or "No safety data available",
        }
        if candidate.get("stage3_candidate"):
            stage3_genes.append(gene)

    return rubric_by_gene, stage3_data, stage3_genes


def _persist_target_assessment_if_applicable(
    base: Path,
    report_data: dict[str, Any],
) -> list[dict[str, Any]]:
    if not (base / "lr_candidates.json").exists():
        return []

    try:
        from src.agents.drug_target.tools.assessment_output import (
            validate_target_assessment_file,
        )
        from src.agents.drug_target.tools.stage_logic import (
            _prebuild_target_assessment,
        )

        rubric_by_gene, stage3_data, stage3_genes = _target_assessment_inputs(
            report_data
        )
        template_context = report_data.get("template_context", {})
        template_context = template_context if isinstance(template_context, dict) else {}
        stage1_data = template_context.get("stage1_pairs", {})
        stage1_data = stage1_data if isinstance(stage1_data, dict) else {}

        _prebuild_target_assessment(
            base,
            base / "evidence",
            str(report_data.get("disease") or ""),
            rubric_by_gene,
            stage3_data,
            stage1_data,
            stage3_genes,
        )
        validation = validate_target_assessment_file(base)
    except Exception as exc:  # pragma: no cover - defensive envelope
        return [
            {
                "code": "TARGET_ASSESSMENT_WRITE_FAILED",
                "severity": "critical",
                "message": f"target_assessment.json generation failed: {exc}",
                "path": "target_assessment.json",
            }
        ]

    if validation.get("valid"):
        return []
    return [
        {
            "code": "TARGET_ASSESSMENT_INVALID",
            "severity": "critical",
            "message": "target_assessment.json failed contract validation",
            "path": "target_assessment.json",
            "errors": validation.get("errors", []),
        }
    ]


def _artifact_validation(
    base: Path,
    report_data: dict[str, Any],
    *,
    require_part4: bool = True,
) -> dict[str, Any]:
    issues = validate_report_data(report_data)
    artifacts: dict[str, dict[str, Any]] = {}
    required_artifacts = [
        "report_data.json",
        "drug.md",
        "drug_report.html",
        "drug_report_render.json",
    ]
    if require_part4:
        required_artifacts.extend(
            [PART4_CANDIDATE_SELECTION_FILENAME, PART4_SYNTHESIS_FILENAME]
        )
    if (base / "lr_candidates.json").exists():
        required_artifacts.append("target_assessment.json")
    for name in required_artifacts:
        path = base / name
        metadata: dict[str, Any] = {
            "path": name,
            "exists": path.exists(),
        }
        if path.exists():
            metadata["size_bytes"] = path.stat().st_size
            metadata["sha256"] = _sha256_path(path)
        else:
            issues.append(
                {
                    "code": "MISSING_REQUIRED_ARTIFACT",
                    "severity": "critical",
                    "message": f"Required report artifact is missing: {name}",
                    "path": name,
                }
            )
        artifacts[name] = metadata

    for name in ("drug.md", "drug_report.html", PART4_SYNTHESIS_FILENAME):
        path = base / name
        if not path.exists():
            continue
        if "EXPAND" in path.read_text(encoding="utf-8"):
            issues.append(
                {
                    "code": "UNEXPANDED_PLACEHOLDER",
                    "severity": "critical",
                    "message": f"{name} must not contain EXPAND markers",
                    "path": name,
                }
            )

    return {
        "schema_version": "drug_target.report_validation.v1",
        "valid": not issues,
        "created_at": _utc_now(),
        "data_dir": str(base),
        "artifacts": artifacts,
        "issues": issues,
    }


def _add_self_validation_artifact(validation: dict[str, Any]) -> dict[str, Any]:
    artifacts = validation.setdefault("artifacts", {})
    if isinstance(artifacts, dict):
        artifacts["report_validation.json"] = {
            "path": "report_validation.json",
            "exists": True,
        }
    return validation


def _write_deterministic_render_metadata(base: Path, markdown: str) -> None:
    source_paths: dict[str, str | None] = {
        "report_data": "report_data.json",
        "reference_card": (
            "drug_report_reference_card.json"
            if (base / "drug_report_reference_card.json").exists()
            else None
        ),
        "report_expansions": (
            "report_expansions.json"
            if (base / "report_expansions.json").exists()
            else None
        ),
    }
    source_hashes = {
        key: _sha256_path(base / path)
        for key, path in source_paths.items()
        if path is not None and (base / path).exists()
    }
    _write_json(
        base / "drug_report_render.json",
        {
            "schema_version": "drug_report_render.v1",
            "renderer": "deterministic_report.render_report_markdown",
            "mode": "deterministic",
            "source_paths": source_paths,
            "source_hashes": source_hashes,
            "rendered_drug_md_sha256": _sha256_text(markdown),
            "required_slot_count": 0,
            "rendered_slot_count": 0,
            "missing_slots": [],
            "extra_slots": [],
            "pagination_warnings": [],
            "created_at": _utc_now(),
        },
    )


def _write_hybrid_render_metadata(base: Path, markdown: str) -> None:
    source_paths = {
        "report_sections": REPORT_SECTIONS_FILENAME,
        "report_data": "report_data.json",
        "target_assessment": "target_assessment.json",
    }
    _write_json(
        base / "drug_report_render.json",
        {
            "schema_version": "drug_report_render.v1",
            "renderer": "deterministic_report.render_hybrid_report",
            "mode": "hybrid_jinja_qwen",
            "source_paths": source_paths,
            "source_hashes": {
                key: _sha256_path(base / path)
                for key, path in source_paths.items()
                if (base / path).exists()
            },
            "rendered_drug_md_sha256": _sha256_text(markdown),
            "required_slot_count": 0,
            "rendered_slot_count": 0,
            "missing_slots": [],
            "extra_slots": [],
            "pagination_warnings": [],
            "created_at": _utc_now(),
        },
    )


def render_report_markdown(
    report_data: dict[str, Any],
    interpretations: dict[str, Any] | None = None,
    *,
    pipeline_recommendations: Sequence[Mapping[str, str]] = (),
) -> str:
    template_str = _markdown_template_path().read_text(encoding="utf-8")
    env = Environment(
        loader=BaseLoader(),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    context = _markdown_template_context(report_data, interpretations=interpretations)
    context["pipeline_recommendations"] = [
        dict(recommendation) for recommendation in pipeline_recommendations
    ]
    rendered = env.from_string(template_str).render(**context)
    return _strip_expand_markers(rendered)


def render_hybrid_report(
    data_dir: str,
    disease: str,
    report_sections: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Render renderer-owned artifacts from an already-canonical sections payload."""

    if not isinstance(report_sections, Mapping):
        raise ValueError("report_sections must be a canonical mapping")
    sections = dict(report_sections)
    if sections.get("schema_version") != "hybrid_report_sections/v1":
        raise ValueError("report_sections must use hybrid_report_sections/v1")
    hypothesis_report = sections.get("hypothesis_report")
    recommendations = sections.get("pipeline_recommendations")
    if not isinstance(hypothesis_report, Mapping) or not isinstance(recommendations, list):
        raise ValueError("report_sections must include canonical hypotheses and recommendations")
    if not all(isinstance(recommendation, Mapping) for recommendation in recommendations):
        raise ValueError("pipeline_recommendations must contain mappings")

    base = Path(data_dir).expanduser().resolve()
    _write_json(base / REPORT_SECTIONS_FILENAME, sections)
    report_data = build_report_data(
        str(base),
        disease,
        hypothesis_data=sections,
        hypothesis_source=REPORT_SECTIONS_FILENAME,
    )
    issues = validate_report_data(report_data)
    if issues:
        raise ValueError(f"hybrid report data is invalid: {issues[0]['code']}")
    _write_json(base / "report_data.json", report_data)

    target_assessment_issues = _persist_target_assessment_if_applicable(
        base,
        report_data,
    )
    if target_assessment_issues:
        raise ValueError(
            f"target assessment is invalid: {target_assessment_issues[0]['code']}"
        )
    if not (base / "target_assessment.json").exists():
        raise ValueError("hybrid report rendering requires target_assessment.json")

    markdown = render_report_markdown(
        report_data,
        pipeline_recommendations=recommendations,
    )
    (base / "drug.md").write_text(markdown, encoding="utf-8")
    _write_hybrid_render_metadata(base, markdown)
    return markdown, report_data


async def finalize_report_mvp(state: dict, config: RunnableConfig) -> dict:
    base = Path(state["data_dir"]).expanduser().resolve()
    part4_path = base / PART4_SYNTHESIS_FILENAME
    part4_candidate_selection_path = base / PART4_CANDIDATE_SELECTION_FILENAME
    await asyncio.to_thread(part4_path.unlink, missing_ok=True)
    await asyncio.to_thread(part4_candidate_selection_path.unlink, missing_ok=True)
    await asyncio.to_thread((base / "drug_report_render.json").unlink, missing_ok=True)
    report_data = build_report_data(str(base), str(state.get("disease") or ""))
    _write_json(base / "report_data.json", report_data)

    issues = validate_report_data(report_data)
    if issues:
        validation = _artifact_validation(base, report_data, require_part4=False)
        validation["valid"] = False
        validation["issues"] = issues
        _add_self_validation_artifact(validation)
        _write_json(base / "report_validation.json", validation)
        reason = issues[0].get("code", "UNKNOWN")
        return {
            "report_finalization_error": (
                f"deterministic_report_validation_failed: {reason}"
            ),
            "evidence_truncated": False,
        }

    interpretations: dict[str, Any] | None = None
    interpretations_payload: dict[str, Any] | None = None
    from src.agents.drug_target.report_interpretations import (
        generate_report_interpretations,
        interpretation_provider_from_config,
        report_interpretations_enabled,
        resolve_interpretation_max_attempts,
    )

    if report_interpretations_enabled(config):
        provider = interpretation_provider_from_config(config)
        if provider is not None:
            (
                interpretations_payload,
                interpretations,
            ) = await generate_report_interpretations(
                report_data,
                provider,
                max_attempts=resolve_interpretation_max_attempts(config),
            )
        else:
            interpretations_payload, interpretations = {}, {}
        _write_json(base / "report_interpretations.json", interpretations_payload)

    markdown = render_report_markdown(report_data, interpretations=interpretations)
    (base / "drug.md").write_text(markdown, encoding="utf-8")
    _write_deterministic_render_metadata(base, markdown)
    (base / "drug_report.html").write_text(
        render_report_html(report_data, markdown),
        encoding="utf-8",
    )
    target_assessment_issues = _persist_target_assessment_if_applicable(
        base,
        report_data,
    )

    pre_part4_validation = _artifact_validation(
        base,
        report_data,
        require_part4=False,
    )
    if target_assessment_issues:
        pre_part4_validation["valid"] = False
        pre_part4_validation["issues"].extend(target_assessment_issues)
    if not pre_part4_validation["valid"]:
        _add_self_validation_artifact(pre_part4_validation)
        _write_json(base / "report_validation.json", pre_part4_validation)
        reason = pre_part4_validation["issues"][0].get("code", "UNKNOWN")
        return {
            "report_finalization_error": (
                f"deterministic_report_validation_failed: {reason}"
            ),
            "evidence_truncated": False,
        }

    deterministic_synthesis = build_part4_therapeutic_synthesis(
        report_data,
        validation=pre_part4_validation,
        interpretations_payload=interpretations_payload,
    )
    deterministic_selected_genes = [
        str(candidate.get("gene") or "")
        for candidate in deterministic_synthesis["featured_candidates"]
        if candidate.get("gene")
    ]
    selector_provider = (
        part4_candidate_selector_provider_from_config(config)
        if part4_candidate_selector_enabled(config)
        else None
    )
    candidate_selection_payload = await generate_part4_candidate_selection(
        report_data,
        deterministic_selected_genes=deterministic_selected_genes,
        provider=selector_provider,
        data_dir=base,
        config=config,
    )
    _write_json(part4_candidate_selection_path, candidate_selection_payload)

    part4_synthesis = build_part4_therapeutic_synthesis(
        report_data,
        validation=pre_part4_validation,
        interpretations_payload=interpretations_payload,
        candidate_selection_payload=candidate_selection_payload,
    )
    part4_path.write_text(
        render_part4_therapeutic_synthesis_markdown(part4_synthesis),
        encoding="utf-8",
    )

    validation = _artifact_validation(base, report_data)
    _add_self_validation_artifact(validation)
    _write_json(base / "report_validation.json", validation)
    if not validation["valid"]:
        await asyncio.to_thread(part4_path.unlink, missing_ok=True)
        reason = validation["issues"][0].get("code", "UNKNOWN")
        return {
            "report_finalization_error": (
                f"deterministic_report_validation_failed: {reason}"
            ),
            "evidence_truncated": False,
        }

    return {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
