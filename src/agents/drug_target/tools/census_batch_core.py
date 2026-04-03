"""Shared batch Census logic for L-R pair co-expression validation.

Opens Census once, fetches all unique genes in a single get_anndata() call,
computes per-pair z-test statistics in-memory. ~14x faster than per-pair
subprocess approach.

Used by:
- src/agents/drug_target/tools/census_lr_validation_tools.py (tool layer)
- scripts/run_census_only.py (standalone CLI)
"""

from __future__ import annotations

import csv
import importlib.util
import json
import logging
import math
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Census configuration
# ---------------------------------------------------------------------------

TILEDB_CONFIG = {
    "vfs.s3.request_timeout_ms": "600000",
    "vfs.s3.connect_timeout_ms": "10000",
    "vfs.s3.connect_max_tries": "25",
    "vfs.s3.max_parallel_ops": "16",
    "soma.init_buffer_bytes": "1073741824",
}

DEFAULT_CENSUS_VERSION = os.getenv("CENSUS_VERSION", "2025-11-08")

# Maximum cells before aborting to prevent OOM
DEFAULT_MAX_CELLS = 1_000_000

# ---------------------------------------------------------------------------
# Import z-test math from the skill script (single source of truth)
# ---------------------------------------------------------------------------

_SKILLS_DIR = Path(__file__).resolve().parents[4] / "skills"


def _load_ztest_functions():
    """Lazy-load ZTestResult and two_proportion_z_test from skill script."""
    script_path = (
        _SKILLS_DIR
        / "compare-census-gene-pair-by-cell-type"
        / "scripts"
        / "compare_census_gene_pair_by_cell_type.py"
    )
    if not script_path.exists():
        raise FileNotFoundError(f"Skill script not found: {script_path}")
    spec = importlib.util.spec_from_file_location(
        "compare_census_gene_pair_by_cell_type", script_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for {script_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # Required for @dataclass to resolve module
    spec.loader.exec_module(mod)
    return mod.ZTestResult, mod.two_proportion_z_test


# Cache at module level
_ztest_cache: dict[str, Any] = {}


def _get_ztest():
    """Return (ZTestResult, two_proportion_z_test) with caching."""
    if "loaded" not in _ztest_cache:
        ZTestResult, two_proportion_z_test = _load_ztest_functions()
        _ztest_cache["ZTestResult"] = ZTestResult
        _ztest_cache["two_proportion_z_test"] = two_proportion_z_test
        _ztest_cache["loaded"] = True
    return _ztest_cache["ZTestResult"], _ztest_cache["two_proportion_z_test"]


# ---------------------------------------------------------------------------
# Disease name resolution (moved from census_lr_validation_tools.py)
# ---------------------------------------------------------------------------


def _resolve_disease_name(
    requested: str,
    organism: str = "homo_sapiens",
) -> tuple[str | None, str]:
    """Fuzzy-match disease name against Census MONDO vocabulary."""
    try:
        from src.agents.drug_target.tools.stage_domain_tools import list_census_diseases

        raw = list_census_diseases.invoke({"organism": organism})
        diseases_result = json.loads(raw)
        if not diseases_result.get("executed") or not diseases_result.get("diseases"):
            return None, "none"

        candidates = diseases_result["diseases"]
    except Exception:
        return None, "none"

    req = requested.strip().lower()

    # Exact match (case-insensitive)
    exact = [c for c in candidates if c["label"].strip().lower() == req]
    if exact:
        return exact[0]["label"], "exact"

    # Substring match — request contained in label or vice versa
    partial = [
        c
        for c in candidates
        if req in c["label"].strip().lower() or c["label"].strip().lower() in req
    ]
    if partial:
        best = max(partial, key=lambda x: x["total_cell_count"])
        return best["label"], "fuzzy"

    return None, "none"


# ---------------------------------------------------------------------------
# Z-test result serialization (FIX: use float("inf"), not None)
# ---------------------------------------------------------------------------


def _ztest_to_dict(zr) -> dict[str, Any]:
    """Convert ZTestResult to dict. Emits None for inf/NaN values."""
    result = {
        "target_pct": round(zr.p_target, 6),
        "rest_pct": round(zr.p_rest, 6),
        "diff": round(zr.diff, 6),
        "risk_ratio": round(zr.risk_ratio, 4) if not math.isinf(zr.risk_ratio) else None,
        "z": round(zr.z, 4) if not math.isnan(zr.z) else None,
        "p_value": zr.p_value if not math.isnan(zr.p_value) else None,
    }
    if math.isinf(zr.risk_ratio):
        result["risk_ratio_capped"] = True
    return result


def _json_safe(obj):
    """JSON default handler for non-serializable types."""
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def sanitize_for_json(data):
    """Recursively replace float('inf')/float('nan') with None for JSON serialization."""
    if isinstance(data, dict):
        return {k: sanitize_for_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_for_json(v) for v in data]
    if isinstance(data, float) and (math.isinf(data) or math.isnan(data)):
        return None
    return data


# ---------------------------------------------------------------------------
# Per-pair Census computation (in-memory from AnnData CSR matrix)
# ---------------------------------------------------------------------------


def _compute_pair_census(
    adata,
    cell_types: np.ndarray,
    gene_a: str,
    gene_b: str,
    target_cell_type: str,
    gene_to_idx: dict[str, int],
) -> dict[str, Any]:
    """Compute census z-test statistics for one L-R pair from AnnData CSR matrix."""
    _, two_proportion_z_test = _get_ztest()

    a_idx = gene_to_idx.get(gene_a)
    b_idx = gene_to_idx.get(gene_b)
    if a_idx is None or b_idx is None:
        missing = [g for g in (gene_a, gene_b) if gene_to_idx.get(g) is None]
        return {
            "executed": False,
            "errors": [f"Gene(s) not found in AnnData: {missing}"],
            "target_vs_rest": None,
            "n_target_cells": 0,
            "n_rest_cells": 0,
        }

    # Binary expression vectors
    expr_a = np.asarray(adata.X[:, a_idx].todense()).flatten() > 0
    expr_b = np.asarray(adata.X[:, b_idx].todense()).flatten() > 0
    coexpr = expr_a & expr_b

    # Flag low-confidence when a gene has zero expression across all cells
    low_confidence = not expr_a.any() or not expr_b.any()

    # Target vs rest mask
    target_mask = cell_types == target_cell_type
    rest_mask = ~target_mask
    n_target = int(target_mask.sum())
    n_rest = int(rest_mask.sum())

    MIN_CELLS = 50  # Parity with single-pair path min_cells default
    if n_target == 0:
        return {
            "executed": False,
            "errors": [f"No cells found for cell type '{target_cell_type}'"],
            "target_vs_rest": None,
            "n_target_cells": 0,
            "n_rest_cells": n_rest,
        }
    if n_target < MIN_CELLS:
        return {
            "executed": False,
            "errors": [
                f"Too few cells for cell type '{target_cell_type}': "
                f"{n_target} < {MIN_CELLS} minimum"
            ],
            "target_vs_rest": None,
            "n_target_cells": n_target,
            "n_rest_cells": n_rest,
        }

    # Z-tests for gene_a, gene_b, coexpression
    ztest_a = two_proportion_z_test(
        int(expr_a[target_mask].sum()), n_target,
        int(expr_a[rest_mask].sum()), n_rest,
    )
    ztest_b = two_proportion_z_test(
        int(expr_b[target_mask].sum()), n_target,
        int(expr_b[rest_mask].sum()), n_rest,
    )
    ztest_co = two_proportion_z_test(
        int(coexpr[target_mask].sum()), n_target,
        int(coexpr[rest_mask].sum()), n_rest,
    )

    pair_result: dict[str, Any] = {
        "executed": True,
        "errors": [],
        "target_vs_rest": {
            "gene_a": _ztest_to_dict(ztest_a),
            "gene_b": _ztest_to_dict(ztest_b),
            "coexpression": _ztest_to_dict(ztest_co),
        },
        "n_target_cells": n_target,
        "n_rest_cells": n_rest,
    }
    if low_confidence:
        pair_result["low_confidence"] = True
    return pair_result


# ---------------------------------------------------------------------------
# Per-cell-type CSV row generation (NEW — for _parse_census_csv consumption)
# ---------------------------------------------------------------------------


def _compute_pair_csv_rows(
    adata,
    cell_types: np.ndarray,
    gene_a: str,
    gene_b: str,
    gene_to_idx: dict[str, int],
) -> list[dict[str, Any]]:
    """Compute per-cell-type expression table for CSV writing.

    Returns list of dicts with columns matching _parse_census_csv expectations:
    cell_type, n_cells, gene_a_pos, gene_a_pct, gene_b_pos, gene_b_pct, coexp_pos, coexp_pct
    """
    a_idx = gene_to_idx.get(gene_a)
    b_idx = gene_to_idx.get(gene_b)
    if a_idx is None or b_idx is None:
        return []

    # Binary expression vectors
    expr_a = np.asarray(adata.X[:, a_idx].todense()).flatten() > 0
    expr_b = np.asarray(adata.X[:, b_idx].todense()).flatten() > 0
    coexpr = expr_a & expr_b

    # Count per cell type
    unique_types = np.unique(cell_types)
    rows = []
    for ct in unique_types:
        mask = cell_types == ct
        n_cells = int(mask.sum())
        if n_cells == 0:
            continue
        a_pos = int(expr_a[mask].sum())
        b_pos = int(expr_b[mask].sum())
        co_pos = int(coexpr[mask].sum())
        rows.append({
            "cell_type": str(ct),
            "n_cells": n_cells,
            "gene_a_pos": a_pos,
            "gene_a_pct": round((a_pos / n_cells) * 100.0, 4),
            "gene_b_pos": b_pos,
            "gene_b_pct": round((b_pos / n_cells) * 100.0, 4),
            "coexp_pos": co_pos,
            "coexp_pct": round((co_pos / n_cells) * 100.0, 4),
        })

    # Sort by cell count descending
    rows.sort(key=lambda r: r["n_cells"], reverse=True)
    return rows


def write_census_csv(
    csv_path: Path | str,
    rows: list[dict[str, Any]],
) -> None:
    """Write per-cell-type Census expression data to CSV."""
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "cell_type", "n_cells",
        "gene_a_pos", "gene_a_pct",
        "gene_b_pos", "gene_b_pct",
        "coexp_pos", "coexp_pct",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Main batch function
# ---------------------------------------------------------------------------


def batch_census_lr_pairs(
    pairs: list[tuple[str, str]],
    disease: str,
    target_cell_type: str,
    organism: str = "homo_sapiens",
    census_version: str | None = None,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    """Batch Census L-R co-expression validation.

    Opens Census ONCE, fetches all unique genes in a single get_anndata()
    call, then computes per-pair z-test statistics in-memory.

    Args:
        pairs: List of (gene_a, gene_b) tuples.
        disease: Disease label for Census obs filter.
        target_cell_type: Cell type for target-vs-rest comparison.
        organism: Census organism key.
        census_version: Pinned Census version.
        max_cells: Hard cap on cell count to prevent OOM.

    Returns:
        Tuple of:
        - List of per-pair result dicts (matching run_compare_census_lr_pair schema)
        - Dict mapping (gene_a, gene_b) to CSV row lists for file writing
    """
    import cellxgene_census

    census_version = census_version or DEFAULT_CENSUS_VERSION

    # Disease resolution
    disease_resolved = None
    disease_resolution_mode = None
    try:
        resolved, mode = _resolve_disease_name(disease, organism)
        if resolved and resolved != disease:
            disease_resolved = resolved
            disease_resolution_mode = mode
            disease = resolved
    except Exception as exc:
        logger.debug("Disease resolution failed: %s", exc)

    # Collect all unique genes
    all_genes: set[str] = set()
    for gene_a, gene_b in pairs:
        all_genes.add(gene_a)
        all_genes.add(gene_b)
    unique_genes = sorted(all_genes)

    logger.info(
        "Census batch: %d pairs, %d unique genes, disease=%r, cell_type=%r",
        len(pairs), len(unique_genes), disease, target_cell_type,
    )

    results: list[dict[str, Any]] = []
    csv_data: dict[tuple[str, str], list[dict[str, Any]]] = {}

    with cellxgene_census.open_soma(
        census_version=census_version, tiledb_config=TILEDB_CONFIG,
    ) as census:
        # Step 1: Get obs metadata with disease filter
        disease_safe = disease.replace("\\", "\\\\").replace("'", "\\'")
        obs = cellxgene_census.get_obs(
            census,
            organism,
            value_filter=f"disease == '{disease_safe}' and is_primary_data == True",
            column_names=["soma_joinid", "cell_type", "disease"],
        )

        # Handle || delimiter in Census 2025-11-08
        obs = obs[
            obs["disease"].apply(
                lambda d: disease.lower()
                in [x.strip().lower() for x in str(d).split("||")]
            )
        ]
        logger.info("Census obs: %d cells for disease=%r", len(obs), disease)

        if len(obs) == 0:
            # Return all pairs as failed
            for gene_a, gene_b in pairs:
                results.append(_make_pair_envelope(
                    disease=disease,
                    gene_a=gene_a,
                    gene_b=gene_b,
                    target_cell_type=target_cell_type,
                    census_version=census_version,
                    disease_resolved=disease_resolved,
                    disease_resolution_mode=disease_resolution_mode,
                    pair_result={
                        "executed": False,
                        "errors": [f"No cells found for disease '{disease}'"],
                        "target_vs_rest": None,
                        "n_target_cells": 0,
                        "n_rest_cells": 0,
                    },
                ))
            return results, csv_data

        # Hard memory cap
        if len(obs) > max_cells:
            raise MemoryError(
                f"Census query returned {len(obs)} cells, exceeding {max_cells} cap. "
                f"Pass max_cells= to override."
            )

        obs_ids = obs["soma_joinid"].values

        # Step 2: Get AnnData for all unique genes
        gene_list = "[" + ",".join(f"'{g}'" for g in unique_genes) + "]"
        adata = cellxgene_census.get_anndata(
            census,
            organism=organism,
            obs_coords=obs_ids,
            var_value_filter=f"feature_name in {gene_list}",
            obs_column_names=["cell_type"],
        )
        logger.info("Census AnnData: %dx%d", adata.shape[0], adata.shape[1])

        # Build gene → column index mapping
        gene_to_idx: dict[str, int] = {}
        for i, name in enumerate(adata.var["feature_name"]):
            gene_to_idx[name] = i
        missing_genes = [g for g in unique_genes if g not in gene_to_idx]
        if missing_genes:
            logger.warning("Genes not found in Census: %s", missing_genes)

        cell_types = adata.obs["cell_type"].values

        # Fuzzy cell-type resolution (parity with single-pair path)
        unique_cts = np.unique(cell_types)
        cell_type_resolution_mode = "exact"
        resolved_cell_type = target_cell_type
        if target_cell_type not in unique_cts:
            req = target_cell_type.strip().lower()
            # Try substring/partial match (same logic as _resolve_interest_cell_type)
            partial = [
                ct for ct in unique_cts
                if req in str(ct).strip().lower() or str(ct).strip().lower() in req
            ]
            if partial:
                # Pick the one with most cells
                ct_counts = {str(ct): int((cell_types == ct).sum()) for ct in partial}
                resolved_cell_type = max(ct_counts, key=ct_counts.get)
                cell_type_resolution_mode = "fuzzy"
                logger.info(
                    "Census batch: resolved cell type %r -> %r (fuzzy, %d cells)",
                    target_cell_type, resolved_cell_type, ct_counts[resolved_cell_type],
                )
            else:
                logger.warning(
                    "Census batch: cell type %r not found among %d unique types",
                    target_cell_type, len(unique_cts),
                )

        # Step 3: Compute per-pair statistics and CSV rows
        for gene_a, gene_b in pairs:
            pair_result = _compute_pair_census(
                adata, cell_types, gene_a, gene_b, resolved_cell_type, gene_to_idx,
            )
            # Attach resolution metadata for envelope
            pair_result["resolved_cell_type"] = resolved_cell_type
            pair_result["resolution_mode"] = cell_type_resolution_mode
            csv_rows = _compute_pair_csv_rows(
                adata, cell_types, gene_a, gene_b, gene_to_idx,
            )
            csv_data[(gene_a, gene_b)] = csv_rows

            results.append(_make_pair_envelope(
                disease=disease,
                gene_a=gene_a,
                gene_b=gene_b,
                target_cell_type=target_cell_type,
                census_version=census_version,
                disease_resolved=disease_resolved,
                disease_resolution_mode=disease_resolution_mode,
                pair_result=pair_result,
            ))

    return results, csv_data


def _make_pair_envelope(
    *,
    disease: str,
    gene_a: str,
    gene_b: str,
    target_cell_type: str,
    census_version: str,
    disease_resolved: str | None,
    disease_resolution_mode: str | None,
    pair_result: dict[str, Any],
) -> dict[str, Any]:
    """Wrap pair result in the full output envelope matching run_compare_census_lr_pair schema."""
    envelope = {
        "disease": disease,
        "gene_a": gene_a,
        "gene_b": gene_b,
        "requested_cell_type": target_cell_type,
        "resolved_cell_type": pair_result.pop("resolved_cell_type", target_cell_type),
        "resolution_mode": pair_result.pop("resolution_mode", "exact"),
        "census_version": census_version,
        **pair_result,
    }
    if disease_resolved:
        envelope["disease_resolved"] = disease_resolved
        envelope["disease_resolution_mode"] = disease_resolution_mode
    return envelope
