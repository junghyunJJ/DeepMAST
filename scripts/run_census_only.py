#!/usr/bin/env python3
"""Batch Census data collection for Stage 1 L-R pairs using get_anndata().

Opens Census once, fetches all unique genes in a single query, then computes
per-pair statistics in-memory. ~14x faster than per-pair subprocess approach.

Usage:
    python scripts/run_census_only.py res_ipf_qwen "idiopathic pulmonary fibrosis" "pulmonary alveolar type 2 cell"
"""

from __future__ import annotations

import glob
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.tools.census_batch_core import (
    DEFAULT_CENSUS_VERSION,
    TILEDB_CONFIG,
    _compute_pair_census,
    _compute_pair_csv_rows,
    _json_safe,
    _ztest_to_dict,
    write_census_csv,
)


def _sanitize_token(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text.strip()).strip("_").lower() or "unknown"


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python scripts/run_census_only.py <data_dir> <disease> [cell_type]")
        sys.exit(1)

    data_dir = sys.argv[1]
    disease = sys.argv[2]
    cell_type = sys.argv[3] if len(sys.argv) > 3 else "pulmonary alveolar type 2 cell"

    evidence_dir = Path(data_dir) / "evidence"
    stage1_files = sorted(glob.glob(str(evidence_dir / "stage1_*.json")))

    # Load pairs from stage1 files
    pairs: list[tuple[str, str, Path]] = []
    all_genes: set[str] = set()
    for f in stage1_files:
        with open(f) as fh:
            stage1 = json.load(fh)
        ligand = stage1.get("ligand", "")
        receptor = stage1.get("receptor", "")
        if not ligand or not receptor:
            continue
        if stage1.get("census_validation") is not None:
            print(f"SKIP {ligand}-{receptor}: census_validation already exists")
            continue
        pairs.append((ligand, receptor, Path(f)))
        all_genes.update([ligand, receptor])

    if not pairs:
        print("No pairs need Census data.")
        return

    unique_genes = sorted(all_genes)
    print(f"Census batch query: {len(pairs)} pairs, {len(unique_genes)} unique genes")
    print(f"Disease: {disease}")
    print(f"Target cell type: {cell_type}")
    print(f"Genes: {unique_genes}")
    print()

    import cellxgene_census

    total_start = time.time()

    with cellxgene_census.open_soma(
        census_version=DEFAULT_CENSUS_VERSION, tiledb_config=TILEDB_CONFIG
    ) as census:
        # Step 1: Get obs metadata with disease filter
        t = time.time()
        obs = cellxgene_census.get_obs(
            census,
            "homo_sapiens",
            value_filter=f"disease == '{disease}' and is_primary_data == True",
            column_names=["soma_joinid", "cell_type", "disease"],
        )
        # Handle || delimiter in Census 2025-11-08
        obs = obs[
            obs["disease"].apply(
                lambda d: disease.lower()
                in [x.strip().lower() for x in str(d).split("||")]
            )
        ]
        print(f"[1/3] obs metadata: {len(obs)} cells ({time.time() - t:.1f}s)")

        if len(obs) == 0:
            print(f"ERROR: No cells found for disease '{disease}'")
            return

        if len(obs) > 500_000:
            print(f"WARNING: {len(obs)} cells exceeds 500K — query may be slow")

        # Cell type distribution
        ct_counts = Counter(obs["cell_type"])
        target_count = ct_counts.get(cell_type, 0)
        print(f"  Target '{cell_type}': {target_count} cells")
        if target_count == 0:
            print(f"  Available types: {[f'{k} ({v})' for k, v in ct_counts.most_common(10)]}")

        obs_ids = obs["soma_joinid"].values

        # Step 2: Get AnnData for all unique genes
        t = time.time()
        gene_list = "[" + ",".join(f"'{g}'" for g in unique_genes) + "]"
        adata = cellxgene_census.get_anndata(
            census,
            organism="homo_sapiens",
            obs_coords=obs_ids,
            var_value_filter=f"feature_name in {gene_list}",
            obs_column_names=["cell_type"],
        )
        print(f"[2/3] get_anndata: {adata.shape[0]}x{adata.shape[1]} ({time.time() - t:.1f}s)")

        # Build gene → column index mapping (var_names are numeric, use feature_name)
        gene_to_idx: dict[str, int] = {}
        for i, name in enumerate(adata.var["feature_name"]):
            gene_to_idx[name] = i
        missing_genes = [g for g in unique_genes if g not in gene_to_idx]
        if missing_genes:
            print(f"  WARNING: genes not found in Census: {missing_genes}")

        cell_types = adata.obs["cell_type"].values

        # Step 3: Compute per-pair statistics
        t = time.time()
        ok = 0
        fail = 0
        for ligand, receptor, filepath in pairs:
            result = _compute_pair_census(
                adata, cell_types, ligand, receptor, cell_type, gene_to_idx,
            )
            # Build full output schema matching run_compare_census_lr_pair
            census_data = {
                "data_dir": str(Path(data_dir).resolve()),
                "disease": disease,
                "gene_a": ligand,
                "gene_b": receptor,
                "requested_cell_type": cell_type,
                "resolved_cell_type": cell_type,
                "resolution_mode": "exact",
                "census_version": DEFAULT_CENSUS_VERSION,
                **result,
            }

            with open(filepath) as fh:
                stage1 = json.load(fh)
            stage1["census_validation"] = census_data
            with open(filepath, "w") as fh:
                json.dump(stage1, fh, indent=2, default=_json_safe)

            # Write per-pair CSV
            csv_name = f"census_{ligand.lower()}_{receptor.lower()}_{_sanitize_token(cell_type)}.csv"
            csv_path = evidence_dir / csv_name
            csv_rows = _compute_pair_csv_rows(adata, cell_types, ligand, receptor, gene_to_idx)
            if csv_rows:
                write_census_csv(csv_path, csv_rows)

            status = "OK" if result.get("executed") else f"FAIL: {result.get('errors', [])}"
            print(f"  {ligand}-{receptor}: {status}")
            if result.get("executed"):
                ok += 1
            else:
                fail += 1

        print(f"[3/3] pair stats: {ok + fail} pairs ({time.time() - t:.1f}s)")

    total = time.time() - total_start
    print(f"\nDone in {total:.1f}s: {ok} OK, {fail} failed")


if __name__ == "__main__":
    main()
