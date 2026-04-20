"""Helpers to normalize legacy Stage 1 evidence artifacts."""

from __future__ import annotations

import csv
import json
import logging
import math
import re
from pathlib import Path
from statistics import NormalDist
from typing import Any

from langchain_core.tools import tool
from src.agents.drug_target.tools.stage2_service import extract_lr_pairs

from src.agents.drug_target.tools.census_batch_core import (
    batch_census_lr_pairs as _batch_census_lr_pairs,
    write_census_csv as _write_census_csv,
)
from src.agents.drug_target.tools.census_lr_validation_tools import (
    run_compare_census_lr_pair,
)
from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir
from src.agents.drug_target.tools.stage_logic import compute_stage1_filter


# Circuit-breaker: track consecutive finalize failures per data_dir
_FINALIZE_CALL_COUNT: dict[str, int] = {}

DEFAULT_CENSUS_DISEASE = "breast carcinoma"
DEFAULT_TARGET_CELL_TYPE = "mammary gland epithelial cell"
DEFAULT_LEGACY_TARGET_CELL_TYPE = "malignant cell"
MICROENVIRONMENT_CONTEXT_TYPE = "vascular"
MICROENVIRONMENT_KEYWORDS = ("endothelial", "vascular", "pericyte")
MICROENVIRONMENT_TARGET_COEXP_MAX_PCT = 0.1
MICROENVIRONMENT_SUPPORT_MIN_PCT = 10.0
STAGE1_SKIP_FILES = frozenset({
    "stage1_evidence.json",
    "stage1_filter.json",
    "stage1_audit.json",
})


def _sanitize_token(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _pick_first_nonempty(*candidates: tuple[Any, str]) -> tuple[str, str] | tuple[None, None]:
    for value, source in candidates:
        text = _clean_text(value)
        if text:
            return text, source
    return None, None


def _extract_targets_interest_cell_type(targets_data: dict[str, Any]) -> str:
    interest = targets_data.get("interest_celltypes", [])
    if isinstance(interest, str):
        return _clean_text(interest)
    if isinstance(interest, list):
        for item in interest:
            text = _clean_text(item)
            if text:
                return text
    return ""


def _extract_census_context(payload: dict[str, Any]) -> dict[str, str]:
    census = payload.get("census_validation", {})
    if not isinstance(census, dict):
        return {}
    return {
        "disease": _clean_text(census.get("disease")),
        "requested_target_cell_type": _clean_text(census.get("requested_cell_type")),
        "resolved_target_cell_type": _clean_text(census.get("resolved_cell_type")),
    }


def _load_input_lr_pairs(data_dir: str | Path) -> list[tuple[str, str]]:
    data_dir = Path(data_dir)
    lr_data = _read_json_if_exists(data_dir / "lr_candidates.json")
    pairs = extract_lr_pairs(lr_data)

    unique_pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        ligand = _clean_text(pair.get("ligand") or pair.get("source")).upper()
        receptor = _clean_text(pair.get("receptor") or pair.get("target")).upper()
        if not ligand or not receptor:
            continue
        item = (ligand, receptor)
        if item in seen:
            continue
        seen.add(item)
        unique_pairs.append(item)
    return unique_pairs


def _pair_key(ligand: str, receptor: str) -> str:
    return f"{ligand.upper()}^{receptor.upper()}"


def _stage1_detail_path(evidence_dir: Path, ligand: str, receptor: str) -> Path:
    return evidence_dir / f"stage1_{ligand.upper()}--{receptor.upper()}.json"


def _stage1_csv_path(
    evidence_dir: Path,
    ligand: str,
    receptor: str,
    csv_target_cell_type: str,
) -> Path:
    return evidence_dir / (
        f"census_{ligand.lower()}_{receptor.lower()}_{_sanitize_token(csv_target_cell_type)}.csv"
    )


def parse_stage1_pair_from_filename(path: str | Path) -> tuple[str, str]:
    """Recover ligand/receptor symbols from a stage1_<ligand>--<receptor>.json file."""
    stem = Path(path).stem
    if not stem.startswith("stage1_"):
        raise ValueError(f"Not a Stage1 file: {path}")

    pair = stem.removeprefix("stage1_")
    if "--" not in pair:
        raise ValueError(f"Cannot infer ligand/receptor from: {path}")

    ligand, receptor = pair.split("--", 1)
    if not ligand or not receptor:
        raise ValueError(f"Invalid Stage1 filename: {path}")
    return ligand.upper(), receptor.upper()


def _validate_stage1_dict(data: Any, path: Path) -> dict[str, Any]:
    """Ensure parsed JSON is a dict, raising ValueError otherwise."""
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def load_stage1_json(path: str | Path) -> tuple[dict[str, Any], list[str]]:
    """Load Stage1 JSON with repairs for common LLM writing errors."""
    path = Path(path)
    raw = path.read_text()
    repairs: list[str] = []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        text = raw.strip()

        # Repair 1: Remove trailing commas before } or ]
        repaired = re.sub(r',\s*([}\]])', r'\1', text)
        if repaired != text:
            try:
                data = json.loads(repaired)
                repairs.append("removed_trailing_commas")
                return _validate_stage1_dict(data, path), repairs
            except json.JSONDecodeError:
                text = repaired  # keep the comma fix, continue to brace repair

        # Repair 2: Trim extra closing braces
        if text.count("}") > text.count("{"):
            candidate = text
            while candidate.endswith("}") and candidate.count("}") > candidate.count("{"):
                candidate = candidate[:-1]
                try:
                    data = json.loads(candidate)
                    repairs.append("trimmed_extra_closing_brace")
                    return _validate_stage1_dict(data, path), repairs
                except json.JSONDecodeError:
                    continue

        raise  # re-raise original error if all repairs fail

    return _validate_stage1_dict(data, path), repairs


def _load_existing_stage1_context(evidence_dir: Path) -> dict[str, str]:
    aggregate = _read_json_if_exists(evidence_dir / "stage1_evidence.json")
    for pair_key in sorted(aggregate):
        item = aggregate.get(pair_key)
        if isinstance(item, dict):
            context = _extract_census_context(item)
            if any(context.values()):
                return context

    for path in sorted(evidence_dir.glob("stage1_*.json")):
        if path.name in STAGE1_SKIP_FILES:
            continue
        try:
            detail, _ = load_stage1_json(path)
        except Exception:
            continue
        context = _extract_census_context(detail)
        if any(context.values()):
            return context

    return {}


def resolve_stage1_context(
    data_dir: str | Path,
    *,
    disease: str | None = None,
    target_cell_type: str | None = None,
    allow_existing_evidence_fallback: bool = False,
    allow_existing_stage1_fallback: bool | None = None,
    prefer_existing_stage1_target: bool = False,
) -> dict[str, str]:
    """Resolve disease and target-cell metadata for Stage1 consumers."""
    data_dir = Path(data_dir)
    evidence_dir = data_dir / "evidence"
    if allow_existing_stage1_fallback is not None:
        allow_existing_evidence_fallback = allow_existing_stage1_fallback

    lr_data = _read_json_if_exists(data_dir / "lr_candidates.json")
    targets_data = _read_json_if_exists(data_dir / "targets.json")
    target_assessment = _read_json_if_exists(data_dir / "target_assessment.json")
    known_drugs = _read_json_if_exists(evidence_dir / "known_drugs.json")
    existing = _load_existing_stage1_context(evidence_dir) if allow_existing_evidence_fallback else {}

    resolved_disease, disease_source = _pick_first_nonempty(
        (disease, "cli"),
        (lr_data.get("disease"), "lr_candidates.json:disease"),
        (lr_data.get("disease_context"), "lr_candidates.json:disease_context"),
        (
            (target_assessment.get("project_meta") or {}).get("disease_focus"),
            "target_assessment.json:project_meta.disease_focus",
        ),
        (known_drugs.get("disease"), "evidence/known_drugs.json:disease"),
        (
            existing.get("disease"),
            "existing_stage1:census_validation.disease",
        ),
    )
    if not resolved_disease:
        raise ValueError(
            "Could not resolve disease for Stage1 context from CLI or metadata. "
            "Provide --disease or populate lr_candidates.json / target_assessment.json / evidence/known_drugs.json."
        )

    requested_target_cell_type, requested_source = _pick_first_nonempty(
        (target_cell_type, "cli"),
        (
            existing.get("requested_target_cell_type"),
            "existing_stage1:census_validation.requested_cell_type",
        ) if prefer_existing_stage1_target else ("", ""),
        (
            _extract_targets_interest_cell_type(targets_data),
            "targets.json:interest_celltypes[0]",
        ),
        (
            existing.get("requested_target_cell_type"),
            "existing_stage1:census_validation.requested_cell_type",
        ),
        (
            existing.get("resolved_target_cell_type"),
            "existing_stage1:census_validation.resolved_cell_type",
        ),
    )
    if not requested_target_cell_type:
        raise ValueError(
            "Could not resolve target cell type for Stage1 context from CLI or metadata. "
            "Provide --target-cell-type or populate targets.json with interest_celltypes."
        )

    resolved_target_cell_type, resolved_source = _pick_first_nonempty(
        (target_cell_type, "cli"),
        (
            existing.get("resolved_target_cell_type"),
            "existing_stage1:census_validation.resolved_cell_type",
        ),
        (requested_target_cell_type, requested_source or "requested_target_cell_type"),
    )
    csv_target_cell_type, csv_source = _pick_first_nonempty(
        (target_cell_type, "cli"),
        (
            existing.get("requested_target_cell_type"),
            "existing_stage1:census_validation.requested_cell_type",
        ),
        (resolved_target_cell_type, resolved_source or "resolved_target_cell_type"),
    )

    return {
        "disease": resolved_disease,
        "disease_source": disease_source or "",
        "requested_target_cell_type": requested_target_cell_type,
        "requested_target_cell_type_source": requested_source or "",
        "resolved_target_cell_type": resolved_target_cell_type,
        "resolved_target_cell_type_source": resolved_source or "",
        "csv_target_cell_type": csv_target_cell_type,
        "csv_target_cell_type_source": csv_source or "",
        "target_cell_type": resolved_target_cell_type,
        "target_cell_type_source": resolved_source or "",
    }


def _parse_census_csv(csv_path: Path, target_cell_type: str) -> dict[str, Any] | None:
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))

    target_rows = [r for r in rows if r["cell_type"].strip() == target_cell_type]
    # Fuzzy fallback: substring match (safety net if LLM mapping is imprecise)
    if not target_rows:
        req = target_cell_type.strip().lower()
        partial = [
            r for r in rows
            if req in r["cell_type"].strip().lower()
            or r["cell_type"].strip().lower() in req
        ]
        if partial:
            target_rows = [max(partial, key=lambda r: int(r["n_cells"]))]
    rest_rows = [r for r in rows if r not in target_rows]
    if not target_rows:
        return None

    target_row = target_rows[0]
    n_target = int(target_row["n_cells"])
    n_rest = sum(int(r["n_cells"]) for r in rest_rows)
    if n_target == 0 or n_rest == 0:
        return None

    def _ztest(pos_col: str) -> dict[str, Any]:
        pos_target = int(target_row[pos_col])
        pos_rest = sum(int(r[pos_col]) for r in rest_rows)
        p_target = pos_target / n_target
        p_rest = pos_rest / n_rest

        # 0/0 produces a non-RFC-8259 JSON value when serialized as float("inf").
        # Emit None + an explicit `risk_ratio_capped` flag so downstream JSON
        # parsers, reports, and schema validators see a well-formed value.
        if p_rest > 0:
            risk_ratio: float | None = round(p_target / p_rest, 4)
            risk_ratio_capped = False
        else:
            risk_ratio = None
            risk_ratio_capped = True
        pooled = (pos_target + pos_rest) / (n_target + n_rest)
        if 0 < pooled < 1:
            se = math.sqrt(pooled * (1 - pooled) * (1 / n_target + 1 / n_rest))
            z_score = round((p_target - p_rest) / se, 4) if se > 0 else 0.0
            p_value = 2 * (1 - NormalDist().cdf(abs(z_score)))
        else:
            z_score = 0.0
            p_value = 1.0

        return {
            "target_pct": round(p_target, 6),
            "rest_pct": round(p_rest, 6),
            "diff": round(p_target - p_rest, 6),
            "risk_ratio": risk_ratio,
            "risk_ratio_capped": risk_ratio_capped,
            "z": z_score,
            "p_value": p_value,
        }

    return {
        "gene_a": _ztest("gene_a_pos"),
        "gene_b": _ztest("gene_b_pos"),
        "coexpression": _ztest("coexp_pos"),
    }


def _load_census_summary_rows(csv_path: Path) -> list[dict[str, Any]]:
    rows = []
    with csv_path.open() as f:
        for row in csv.DictReader(f):
            rows.append({
                "cell_type": row["cell_type"].strip(),
                "n_cells": int(row["n_cells"]),
                "gene_a_pct": float(row["gene_a_pct"]),
                "gene_b_pct": float(row["gene_b_pct"]),
                "coexp_pct": float(row["coexp_pct"]),
            })
    return rows


def build_census_validation_from_csv(
    evidence_dir: str | Path,
    ligand: str,
    receptor: str,
    *,
    csv_target_cell_type: str,
    disease: str,
    requested_target_cell_type: str | None = None,
    resolved_target_cell_type: str | None = None,
) -> dict[str, Any] | None:
    """Build latest census_validation payload from a pair-specific CSV."""
    evidence_dir = Path(evidence_dir)
    requested_target_cell_type = _clean_text(requested_target_cell_type) or _clean_text(csv_target_cell_type)
    resolved_target_cell_type = _clean_text(resolved_target_cell_type) or requested_target_cell_type
    csv_target_cell_type = _clean_text(csv_target_cell_type) or resolved_target_cell_type
    csv_path = evidence_dir / (
        f"census_{ligand.lower()}_{receptor.lower()}_{_sanitize_token(csv_target_cell_type)}.csv"
    )
    if not csv_path.exists():
        return None

    target_vs_rest = _parse_census_csv(csv_path, resolved_target_cell_type)
    if target_vs_rest is None and requested_target_cell_type != resolved_target_cell_type:
        target_vs_rest = _parse_census_csv(csv_path, requested_target_cell_type)
        if target_vs_rest is not None:
            resolved_target_cell_type = requested_target_cell_type
    if target_vs_rest is None:
        return None

    return {
        "disease": disease,
        "requested_cell_type": requested_target_cell_type,
        "resolved_cell_type": resolved_target_cell_type,
        "resolution_mode": "exact",
        "target_vs_rest": target_vs_rest,
        "executed": True,
        "source": "csv_integration",
        "csv_file": csv_path.name,
    }


def build_microenvironment_support_from_csv(
    evidence_dir: str | Path,
    ligand: str,
    receptor: str,
    *,
    csv_target_cell_type: str,
    resolved_target_cell_type: str | None = None,
) -> dict[str, Any] | None:
    """Find strong vascular/endothelial support outside the primary target cell type."""
    evidence_dir = Path(evidence_dir)
    resolved_target_cell_type = _clean_text(resolved_target_cell_type) or _clean_text(csv_target_cell_type)
    csv_target_cell_type = _clean_text(csv_target_cell_type) or resolved_target_cell_type
    csv_path = evidence_dir / (
        f"census_{ligand.lower()}_{receptor.lower()}_{_sanitize_token(csv_target_cell_type)}.csv"
    )
    if not csv_path.exists():
        return None

    rows = _load_census_summary_rows(csv_path)
    target_row = next((row for row in rows if row["cell_type"] == resolved_target_cell_type), None)
    if target_row is None and resolved_target_cell_type != csv_target_cell_type:
        target_row = next((row for row in rows if row["cell_type"] == csv_target_cell_type), None)
        if target_row is not None:
            resolved_target_cell_type = csv_target_cell_type
    if target_row is None:
        return None

    candidates = [
        row for row in rows
        if row["cell_type"] != resolved_target_cell_type
        and any(keyword in row["cell_type"].lower() for keyword in MICROENVIRONMENT_KEYWORDS)
    ]
    if not candidates:
        return None

    support = max(
        candidates,
        key=lambda row: (row["coexp_pct"], row["gene_a_pct"] + row["gene_b_pct"], row["n_cells"]),
    )
    if target_row["coexp_pct"] > MICROENVIRONMENT_TARGET_COEXP_MAX_PCT:
        return None
    if support["coexp_pct"] < MICROENVIRONMENT_SUPPORT_MIN_PCT:
        return None
    if support["gene_a_pct"] < MICROENVIRONMENT_SUPPORT_MIN_PCT:
        return None
    if support["gene_b_pct"] < MICROENVIRONMENT_SUPPORT_MIN_PCT:
        return None

    return {
        "microenvironment_candidate": True,
        "context_type": MICROENVIRONMENT_CONTEXT_TYPE,
        "supporting_cell_type": support["cell_type"],
        "supporting_gene_a_pct": round(support["gene_a_pct"], 4),
        "supporting_gene_b_pct": round(support["gene_b_pct"], 4),
        "supporting_coexpression_pct": round(support["coexp_pct"], 4),
        "supporting_csv": csv_path.name,
        "reason": (
            "Primary target-cell coexpression is weak while vascular/endothelial support is strong"
        ),
    }


def build_legacy_target_vs_rest_from_csv(
    evidence_dir: str | Path,
    ligand: str,
    receptor: str,
    *,
    target_cell_type: str = DEFAULT_LEGACY_TARGET_CELL_TYPE,
) -> dict[str, Any] | None:
    """Build target-vs-rest summary from the legacy unknown.csv export."""
    evidence_dir = Path(evidence_dir)
    csv_path = evidence_dir / f"census_{ligand.lower()}_{receptor.lower()}_unknown.csv"
    if not csv_path.exists():
        return None
    return _parse_census_csv(csv_path, target_cell_type)


def normalize_stage1_record(
    data: dict[str, Any],
    *,
    ligand: str,
    receptor: str,
    evidence_dir: str | Path,
    requested_target_cell_type: str,
    disease: str,
    resolved_target_cell_type: str | None = None,
    csv_target_cell_type: str | None = None,
    disease_source: str | None = None,
    target_cell_type_source: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize legacy Stage1 JSON into the latest scoring schema."""
    requested_target_cell_type = _clean_text(requested_target_cell_type)
    resolved_target_cell_type = _clean_text(resolved_target_cell_type) or requested_target_cell_type
    csv_target_cell_type = _clean_text(csv_target_cell_type) or requested_target_cell_type
    normalized = dict(data)
    legacy_stage1: dict[str, Any] = {}
    normalized.pop("stage1_annotations", None)

    if "legacy_stage1" in normalized and isinstance(normalized["legacy_stage1"], dict):
        legacy_stage1.update(normalized["legacy_stage1"])

    legacy_cellxgene = normalized.pop("cellxgene_context", None)
    if legacy_cellxgene is not None:
        legacy_stage1["cellxgene_context"] = legacy_cellxgene

    legacy_census = normalized.pop("census_cross_validation", None)
    if legacy_census is not None:
        legacy_stage1["census_cross_validation"] = legacy_census

    normalized["ligand"] = ligand.upper()
    normalized["receptor"] = receptor.upper()

    latest_census = build_census_validation_from_csv(
        evidence_dir,
        ligand,
        receptor,
        csv_target_cell_type=csv_target_cell_type,
        requested_target_cell_type=requested_target_cell_type,
        resolved_target_cell_type=resolved_target_cell_type,
        disease=disease,
    )
    if latest_census is not None:
        normalized["census_validation"] = latest_census
    else:
        normalized.setdefault("census_validation", {"executed": False})

    # Remove legacy fields no longer used
    normalized.pop("cellxgene", None)
    normalized.pop("kegg_pathways", None)
    normalized.pop("reactome_pathways", None)

    if legacy_stage1:
        normalized["legacy_stage1"] = legacy_stage1

    stage1_filter = compute_stage1_filter(normalized)
    normalized["stage1_filter"] = stage1_filter

    audit = {
        "pair_key": f"{ligand.upper()}^{receptor.upper()}",
        "resolved_disease": disease,
        "disease_source": disease_source,
        "resolved_target_cell_type": resolved_target_cell_type,
        "latest_target_cell_type": (
            normalized.get("census_validation", {}).get("resolved_cell_type")
            or normalized.get("census_validation", {}).get("requested_cell_type")
        ),
        "target_cell_type_source": target_cell_type_source,
        "requested_target_cell_type": requested_target_cell_type,
        "legacy_target_cell_type": (
            legacy_stage1.get("census_cross_validation", {}).get("target_cell_type")
            if legacy_stage1 else None
        ),
        "latest_coexpression": (
            normalized.get("census_validation", {})
            .get("target_vs_rest", {})
            .get("coexpression")
        ),
        "legacy_coexpression": (
            legacy_stage1.get("census_cross_validation", {}).get("coexpression")
            if legacy_stage1 else None
        ),
        "legacy_unknown_csv": build_legacy_target_vs_rest_from_csv(
            evidence_dir,
            ligand,
            receptor,
            target_cell_type=(
                legacy_stage1.get("census_cross_validation", {}).get("target_cell_type")
                if legacy_stage1 else DEFAULT_LEGACY_TARGET_CELL_TYPE
            ),
        ),
        "stage1_filter": stage1_filter,
    }
    return normalized, audit


def rebuild_stage1_artifacts(
    data_dir: str | Path,
    *,
    target_cell_type: str | None = None,
    disease: str | None = None,
    pair_subset: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Normalize per-pair Stage1 files and rebuild aggregated artifacts.

    Args:
        pair_subset: If provided, rebuild only for these (ligand, receptor)
            pairs.  Files for pairs outside the subset are ignored.
    """
    data_dir = Path(data_dir)
    evidence_dir = data_dir / "evidence"
    context = resolve_stage1_context(
        data_dir,
        disease=disease,
        target_cell_type=target_cell_type,
        allow_existing_evidence_fallback=True,
        prefer_existing_stage1_target=True,
    )
    stage1_files = sorted(
        path for path in evidence_dir.glob("stage1_*.json")
        if path.name not in STAGE1_SKIP_FILES
    )
    # When pair_subset is provided, keep only files matching the subset.
    if pair_subset is not None:
        subset_keys = {_pair_key(lig, rec) for lig, rec in pair_subset}
        filtered: list[Path] = []
        for path in stage1_files:
            # Filename pattern: stage1_{LIGAND}--{RECEPTOR}.json
            stem = path.stem  # e.g. "stage1_CXCL12--CXCR4"
            parts = stem.split("_", 1)  # ["stage1", "CXCL12--CXCR4"]
            if len(parts) == 2:
                pair_part = parts[1]  # "CXCL12--CXCR4"
                gene_parts = pair_part.split("--", 1)
                if len(gene_parts) == 2:
                    key = _pair_key(gene_parts[0], gene_parts[1])
                    if key in subset_keys:
                        filtered.append(path)
        stage1_files = filtered

    stage1_evidence: dict[str, Any] = {}
    stage1_filter_data: dict[str, Any] = {}
    stage1_audit: dict[str, Any] = {}

    for path in stage1_files:
        data, repairs = load_stage1_json(path)
        ligand = str(data.get("ligand") or "").upper()
        receptor = str(data.get("receptor") or "").upper()
        if not ligand or not receptor:
            ligand, receptor = parse_stage1_pair_from_filename(path)

        normalized, audit = normalize_stage1_record(
            data,
            ligand=ligand,
            receptor=receptor,
            evidence_dir=evidence_dir,
            requested_target_cell_type=context["requested_target_cell_type"],
            resolved_target_cell_type=context["resolved_target_cell_type"],
            csv_target_cell_type=context["csv_target_cell_type"],
            disease=context["disease"],
            disease_source=context["disease_source"],
            target_cell_type_source=context["resolved_target_cell_type_source"],
        )
        if repairs:
            audit["repairs"] = repairs

        pair_key = f"{ligand}^{receptor}"
        path.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")

        entry = {
            "ligand": ligand,
            "receptor": receptor,
            "string_ppi": normalized.get("string_ppi", {}),
            "census_validation": normalized.get("census_validation", {}),
            "stage1_filter": normalized.get("stage1_filter", {}),
        }
        if "legacy_stage1" in normalized:
            entry["legacy_stage1"] = normalized["legacy_stage1"]

        stage1_evidence[pair_key] = entry
        stage1_filter_data[pair_key] = normalized.get("stage1_filter", {})
        stage1_audit[pair_key] = audit

    (evidence_dir / "stage1_evidence.json").write_text(
        json.dumps(stage1_evidence, indent=2) + "\n",
        encoding="utf-8",
    )
    (evidence_dir / "stage1_filter.json").write_text(
        json.dumps(stage1_filter_data, indent=2) + "\n",
        encoding="utf-8",
    )
    (evidence_dir / "stage1_audit.json").write_text(
        json.dumps(stage1_audit, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "context": context,
        "stage1_files": [path.name for path in stage1_files],
        "stage1_evidence": stage1_evidence,
        "stage1_filter": stage1_filter_data,
        "stage1_audit": stage1_audit,
    }


def validate_stage1_artifacts(
    data_dir: str | Path,
    *,
    disease: str | None = None,
    target_cell_type: str | None = None,
    pair_subset: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Validate that Stage1 artifacts are complete for the expected input pairs.

    Args:
        pair_subset: If provided, validate only these (ligand, receptor) pairs
            instead of all pairs from lr_candidates.json.  Used when Stage 1
            runs only for FEATURED pairs after Stage 2 gene selection.
    """
    data_dir = Path(data_dir)
    evidence_dir = data_dir / "evidence"
    try:
        context = resolve_stage1_context(
            data_dir,
            disease=disease,
            target_cell_type=target_cell_type,
            allow_existing_evidence_fallback=True,
            prefer_existing_stage1_target=True,
        )
    except Exception as exc:
        return {
            "valid": False,
            "context": {},
            "expected_pairs": [],
            "expected_pair_count": 0,
            "missing_detail_files": [],
            "missing_csv_files": [],
            "missing_aggregate_files": [],
            "parse_errors": {},
            "schema_mismatches": {},
            "aggregate_pair_mismatches": {},
            "errors": [str(exc)],
        }
    expected_pairs = pair_subset if pair_subset is not None else _load_input_lr_pairs(data_dir)
    expected_pair_keys = {_pair_key(ligand, receptor) for ligand, receptor in expected_pairs}
    aggregate_paths = {
        "stage1_evidence": evidence_dir / "stage1_evidence.json",
        "stage1_filter": evidence_dir / "stage1_filter.json",
        "stage1_audit": evidence_dir / "stage1_audit.json",
    }

    errors: list[str] = []
    parse_errors: dict[str, str] = {}
    missing_detail_files: list[str] = []
    missing_csv_files: list[str] = []
    schema_mismatches: dict[str, list[str]] = {}
    aggregate_pair_mismatches: dict[str, dict[str, list[str]]] = {}

    for ligand, receptor in expected_pairs:
        pair_key = _pair_key(ligand, receptor)
        detail_path = _stage1_detail_path(evidence_dir, ligand, receptor)
        if not detail_path.exists():
            missing_detail_files.append(detail_path.name)
            continue
        try:
            detail, _ = load_stage1_json(detail_path)
        except Exception as exc:
            parse_errors[detail_path.name] = str(exc)
            continue

        missing_fields = [
            field for field in ("ligand", "receptor", "census_validation", "stage1_filter")
            if field not in detail
        ]
        if detail.get("ligand") != ligand:
            missing_fields.append("ligand_value_mismatch")
        if detail.get("receptor") != receptor:
            missing_fields.append("receptor_value_mismatch")
        census_validation = detail.get("census_validation", {})
        if isinstance(census_validation, dict) and census_validation.get("executed") is False:
            pass  # Census disabled or explicitly not executed — skip validation
        elif not isinstance(census_validation, dict) or "target_vs_rest" not in census_validation:
            missing_fields.append("census_validation.target_vs_rest")
        if missing_fields:
            schema_mismatches[pair_key] = missing_fields

        csv_path = _stage1_csv_path(
            evidence_dir,
            ligand,
            receptor,
            context["csv_target_cell_type"],
        )
        if not csv_path.exists():
            missing_csv_files.append(csv_path.name)

    missing_aggregate_files = [
        path.name for path in aggregate_paths.values() if not path.exists()
    ]
    for aggregate_name, aggregate_path in aggregate_paths.items():
        if not aggregate_path.exists():
            continue
        try:
            aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
        except Exception as exc:
            parse_errors[aggregate_path.name] = str(exc)
            continue
        if not isinstance(aggregate, dict):
            parse_errors[aggregate_path.name] = "aggregate is not a JSON object"
            continue

        found_keys = set(aggregate)
        missing_pairs = sorted(expected_pair_keys - found_keys)
        extra_pairs = sorted(found_keys - expected_pair_keys)
        if missing_pairs or extra_pairs:
            aggregate_pair_mismatches[aggregate_name] = {
                "missing_pairs": missing_pairs,
                "extra_pairs": extra_pairs,
            }

    if not expected_pairs:
        errors.append("No input L-R pairs found in lr_candidates.json")
    if missing_detail_files:
        errors.append("Missing Stage1 detail files")
    if missing_csv_files:
        errors.append("Missing Stage1 census CSV files")
    if missing_aggregate_files:
        errors.append("Missing Stage1 aggregate files")
    if parse_errors:
        errors.append("Stage1 JSON parse failures detected")
    if schema_mismatches:
        errors.append("Stage1 schema mismatches detected")
    if aggregate_pair_mismatches:
        errors.append("Stage1 aggregate pair-set mismatches detected")

    return {
        "valid": not errors,
        "context": context,
        "expected_pairs": [_pair_key(ligand, receptor) for ligand, receptor in expected_pairs],
        "expected_pair_count": len(expected_pairs),
        "missing_detail_files": missing_detail_files,
        "missing_csv_files": missing_csv_files,
        "missing_aggregate_files": missing_aggregate_files,
        "parse_errors": parse_errors,
        "schema_mismatches": schema_mismatches,
        "aggregate_pair_mismatches": aggregate_pair_mismatches,
        "errors": errors,
    }


logger = logging.getLogger(__name__)

_MAX_CONCURRENT_CENSUS = 3  # Each Census subprocess uses ~2.5 GB RAM


def _rerun_missing_census_csvs(
    data_dir: Path,
    *,
    context: dict[str, str],
    missing_csv_files: list[str],
) -> list[dict[str, Any]]:
    evidence_dir = data_dir / "evidence"

    # Separate valid pairs from invalid ones (validation is cheap, do first)
    to_run: list[tuple[str, str, str, Path]] = []  # (csv_name, ligand, receptor, csv_path)
    skipped: list[dict[str, Any]] = []
    for csv_name in missing_csv_files:
        if not csv_name.startswith("census_") or not csv_name.endswith(".csv"):
            skipped.append({
                "csv_file": csv_name,
                "executed": False,
                "errors": ["Unrecognized census CSV naming pattern"],
            })
            continue

        stem = csv_name.removeprefix("census_").removesuffix(".csv")
        prefix = f"_{_sanitize_token(context['csv_target_cell_type'])}"
        if not stem.endswith(prefix):
            skipped.append({
                "csv_file": csv_name,
                "executed": False,
                "errors": ["CSV file does not match resolved Stage1 target cell type"],
            })
            continue
        pair_token = stem[: -len(prefix)]
        # P2-6: defensive parsing — try `--` first (matches stage1_<L>--<R>.json
        # convention used everywhere else), fall back to `_` for back-compat with
        # existing CSV files. Eliminates ambiguity for any future gene symbol
        # containing `_` (rare but not impossible in HGNC).
        if "--" in pair_token:
            ligand, receptor = pair_token.split("--", 1)
        elif "_" in pair_token:
            ligand, receptor = pair_token.split("_", 1)
        else:
            skipped.append({
                "csv_file": csv_name,
                "executed": False,
                "errors": ["Could not infer ligand/receptor from CSV filename"],
            })
            continue
        to_run.append((csv_name, ligand, receptor, evidence_dir / csv_name))

    # Batch Census: single call for all missing pairs
    reruns: list[dict[str, Any]] = list(skipped)
    if to_run:
        pairs = [(ligand.upper(), receptor.upper()) for _, ligand, receptor, _ in to_run]
        csv_paths = {(ligand.upper(), receptor.upper()): csv_path for _, ligand, receptor, csv_path in to_run}
        csv_names = {(ligand.upper(), receptor.upper()): csv_name for csv_name, ligand, receptor, _ in to_run}
        try:
            batch_results, csv_data = _batch_census_lr_pairs(
                pairs=pairs,
                disease=context["disease"],
                target_cell_type=context.get("resolved_target_cell_type") or context["requested_target_cell_type"],
            )
            for result in batch_results:
                pair_key = (result["gene_a"], result["gene_b"])
                csv_name = csv_names.get(pair_key, "")
                csv_path = csv_paths.get(pair_key)
                # Write CSV file
                if csv_path and pair_key in csv_data and csv_data[pair_key]:
                    _write_census_csv(csv_path, csv_data[pair_key])
                result["csv_file"] = csv_name
                result["csv_exists"] = csv_path.exists() if csv_path else False
                reruns.append(result)
        except Exception as exc:
            logger.warning("Batch Census failed, falling back to per-pair: %s", exc)
            for csv_name, ligand, receptor, csv_path in to_run:
                try:
                    raw = run_compare_census_lr_pair.invoke({
                        "data_dir": str(data_dir),
                        "disease": context["disease"],
                        "gene_a": ligand.upper(),
                        "gene_b": receptor.upper(),
                        "target_cell_type": context["requested_target_cell_type"],
                        "output_csv": str(csv_path),
                    })
                    result = json.loads(raw)
                    result["csv_file"] = csv_name
                    result["csv_exists"] = csv_path.exists()
                    reruns.append(result)
                except Exception as fallback_exc:
                    logger.warning("Census rerun failed for %s: %s", csv_name, fallback_exc)
                    reruns.append({
                        "csv_file": csv_name,
                        "executed": False,
                        "errors": [f"Fallback error: {fallback_exc}"],
                    })
    return reruns


def finalize_stage1_workspace(
    data_dir: str | Path,
    *,
    disease: str | None = None,
    target_cell_type: str | None = None,
    rerun_missing_census: bool = True,
    pair_subset: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Deterministically finalize Stage1 artifacts for the current workspace.

    Args:
        pair_subset: If provided, finalize only these (ligand, receptor) pairs
            instead of all pairs from lr_candidates.json.
    """
    data_dir = _resolve_data_dir(str(data_dir))
    pre_validation = validate_stage1_artifacts(
        data_dir,
        disease=disease,
        target_cell_type=target_cell_type,
        pair_subset=pair_subset,
    )
    if not pre_validation.get("context"):
        return {
            "success": False,
            "context": {},
            "rerun_missing_census": rerun_missing_census,
            "rerun_results": [],
            "rebuild": {
                "stage1_files": [],
                "stage1_evidence_path": str(Path(data_dir) / "evidence" / "stage1_evidence.json"),
                "stage1_confidence_path": str(Path(data_dir) / "evidence" / "stage1_filter.json"),
                "stage1_audit_path": str(Path(data_dir) / "evidence" / "stage1_audit.json"),
            },
            "pre_validation": pre_validation,
            "post_validation": pre_validation,
        }
    rerun_results: list[dict[str, Any]] = []
    if rerun_missing_census and pre_validation["missing_csv_files"]:
        rerun_results = _rerun_missing_census_csvs(
            data_dir,
            context=pre_validation["context"],
            missing_csv_files=pre_validation["missing_csv_files"],
        )

    rebuild = rebuild_stage1_artifacts(
        data_dir,
        disease=pre_validation["context"]["disease"],
        target_cell_type=pre_validation["context"]["requested_target_cell_type"],
        pair_subset=pair_subset,
    )
    post_validation = validate_stage1_artifacts(
        data_dir,
        disease=pre_validation["context"]["disease"],
        target_cell_type=pre_validation["context"]["requested_target_cell_type"],
        pair_subset=pair_subset,
    )

    return {
        "success": post_validation["valid"],
        "context": rebuild["context"],
        "rerun_missing_census": rerun_missing_census,
        "rerun_results": rerun_results,
        "rebuild": {
            "stage1_files": rebuild["stage1_files"],
            "stage1_evidence_path": str(Path(data_dir) / "evidence" / "stage1_evidence.json"),
            "stage1_confidence_path": str(Path(data_dir) / "evidence" / "stage1_filter.json"),
            "stage1_audit_path": str(Path(data_dir) / "evidence" / "stage1_audit.json"),
        },
        "pre_validation": pre_validation,
        "post_validation": post_validation,
    }


@tool
def finalize_stage1_artifacts(
    data_dir: str,
    disease: str | None = None,
    target_cell_type: str | None = None,
    rerun_missing_census: bool = True,
    pair_subset_json: str = "",
) -> str:
    """Repair, rebuild, and validate canonical Stage1 artifacts.

    Returns a compact summary (success flag, counts, file paths, errors)
    instead of full validation payloads to keep ToolMessage size small.
    Full details are written to evidence/stage1_*.json files on disk.

    Args:
        pair_subset_json: Optional JSON array of [ligand, receptor] pairs,
            e.g. '[["CXCL12","CXCR4"],["FGF2","FGFR1"]]'.
            When provided, only these pairs are validated/rebuilt instead of
            all pairs from lr_candidates.json.  Use this after Stage 2 gene
            selection when Stage 1 was run only for FEATURED pairs.
    """
    pair_subset = None
    if pair_subset_json:
        try:
            # Handle langchain-ollama already parsed string into list
            if isinstance(pair_subset_json, list):
                raw = pair_subset_json
            else:
                cleaned = str(pair_subset_json).strip()
                # Strip surrounding single quotes (Qwen3.5/Ollama pattern)
                if cleaned.startswith("'") and cleaned.endswith("'"):
                    cleaned = cleaned[1:-1]
                # Handle double-serialized JSON (string-wrapped JSON)
                if cleaned.startswith('"') and cleaned.endswith('"'):
                    try:
                        cleaned = json.loads(cleaned)
                    except (json.JSONDecodeError, TypeError):
                        pass
                raw = json.loads(cleaned) if isinstance(cleaned, str) else cleaned
            pair_subset = [(str(p[0]), str(p[1])) for p in raw]
        except (json.JSONDecodeError, IndexError, TypeError, ValueError):
            truncated = str(pair_subset_json)[:200]
            return json.dumps({
                "success": False,
                "error": f"Invalid pair_subset_json (first 200 chars): {truncated}. "
                         "Expected JSON array of [ligand, receptor] arrays.",
            })

    # Circuit-breaker: resolve canonical key for tracking
    _cb_key = str(Path(data_dir).expanduser().resolve())

    result = finalize_stage1_workspace(
        data_dir,
        disease=disease,
        target_cell_type=target_cell_type,
        rerun_missing_census=rerun_missing_census,
        pair_subset=pair_subset,
    )

    # Circuit-breaker: track consecutive failures per data_dir
    is_success = result.get("success", False)
    # Check whether Stage 3 can still proceed despite finalize failure
    assessment_exists = (Path(data_dir).expanduser().resolve() / "evidence" / "assessment_results.json").exists()
    if is_success:
        _FINALIZE_CALL_COUNT.pop(_cb_key, None)
    else:
        _FINALIZE_CALL_COUNT[_cb_key] = _FINALIZE_CALL_COUNT.get(_cb_key, 0) + 1
        if _FINALIZE_CALL_COUNT[_cb_key] >= 3:
            return json.dumps({
                "abort": True,
                "message": (
                    "Circuit breaker triggered: 3 consecutive finalize failures. "
                    "Check Stage 1 evidence files manually."
                ),
                "success": False,
                "stage3_can_proceed": assessment_exists,
            })

    # Build compact summary to avoid multi-MB ToolMessage payloads
    pre = result.get("pre_validation", {})
    post = result.get("post_validation", {})
    compact: dict[str, Any] = {
        "success": is_success,
        "context": result.get("context", {}),
        "rebuild": result.get("rebuild", {}),
        "rerun_missing_census": result.get("rerun_missing_census", False),
        "rerun_count": len(result.get("rerun_results", [])),
        "pre_validation_summary": {
            "valid": pre.get("valid", False),
            "expected_pair_count": pre.get("expected_pair_count", 0),
            "missing_detail_files": len(pre.get("missing_detail_files", [])),
            "missing_csv_files": len(pre.get("missing_csv_files", [])),
            "missing_aggregate_files": len(pre.get("missing_aggregate_files", [])),
            "parse_errors": len(pre.get("parse_errors", {})),
            "schema_mismatches": len(pre.get("schema_mismatches", {})),
            "errors": pre.get("errors", []),
        },
        "post_validation_summary": {
            "valid": post.get("valid", False),
            "expected_pair_count": post.get("expected_pair_count", 0),
            "missing_detail_files": len(post.get("missing_detail_files", [])),
            "missing_csv_files": len(post.get("missing_csv_files", [])),
            "missing_aggregate_files": len(post.get("missing_aggregate_files", [])),
            "parse_errors": len(post.get("parse_errors", {})),
            "schema_mismatches": len(post.get("schema_mismatches", {})),
            "errors": post.get("errors", []),
        },
    }
    # When finalize fails but assessment_results.json exists, signal that
    # Stage 3 can still proceed (it depends on rubric scores, not Stage 1 artifacts).
    if not is_success and assessment_exists:
        compact["stage3_can_proceed"] = True
    return json.dumps(compact, indent=2)
